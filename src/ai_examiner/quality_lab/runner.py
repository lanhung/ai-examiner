"""Drive full exam conversations through the HTTP API and record results.

Each unit of work is written to ``results.jsonl`` as soon as it finishes, so an
interrupted run resumes where it stopped and several shards can run in parallel
processes and be merged afterwards.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..model_catalog import catalog_entry
from ..providers.base import ProviderResult
from .corpus import Material
from .judge import Judge
from .personas import PERSONAS, llm_answer, rule_based_answer

RULE_ONLY_PERSONAS = frozenset({"dont_know", "bluffer", "injection"})
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


@dataclass
class LabConfig:
    materials: list[Material]
    planner_profiles: list[str]
    analyzer_profiles: list[str]
    judge_profile: str = "mock:heuristic-v2"
    learner_profile: str | None = None
    personas: list[str] = field(default_factory=lambda: list(PERSONAS))
    question_limit: int = 3
    max_followups: int = 1
    repeats: int = 1
    judge_fraction: float = 1.0
    max_cost_usd: float | None = None
    learners_per_blueprint: int = 30
    price_overrides: dict[str, tuple[float, float]] = field(default_factory=dict)
    shard_index: int = 0
    shard_count: int = 1
    out_dir: Path = Path("quality_lab_results")
    max_http_retries: int = 4


class BudgetExceeded(RuntimeError):
    pass


def price(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    overrides: dict[str, tuple[float, float]],
) -> tuple[float, bool]:
    override = overrides.get(f"{provider}:{model}")
    if override:
        rates = override
    elif provider == "mock":
        return 0.0, True
    else:
        entry = catalog_entry(provider, model)
        if entry is None:
            return 0.0, False
        rates = (entry.input_usd_per_million, entry.output_usd_per_million)
    return input_tokens * rates[0] / 1e6 + output_tokens * rates[1] / 1e6, True


def _stable_fraction(key: str) -> float:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _shard_of(material_id: str, count: int) -> int:
    return int(hashlib.sha256(material_id.encode("utf-8")).hexdigest()[:8], 16) % count


class QualityLab:
    def __init__(
        self,
        config: LabConfig,
        client,
        *,
        session_factory,
        provider_factory: Callable[[str], Any],
        log: Callable[[str], None] = print,
    ) -> None:
        self.config = config
        self.client = client
        self.session_factory = session_factory
        self.provider_factory = provider_factory
        self.log = log
        self.config.out_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if config.shard_count == 1 else f".shard{config.shard_index}"
        self.results_path = config.out_dir / f"results{suffix}.jsonl"
        self.records: dict[str, dict] = {}
        if self.results_path.exists():
            for line in self.results_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self.records[record["key"]] = record
        self.spent_usd = sum(
            float(record.get("cost_usd") or 0)
            + float(record.get("judge_cost_usd") or 0)
            + float(record.get("simulation_cost_usd") or 0)
            for record in self.records.values()
        )
        self.judge = Judge(
            None
            if config.judge_profile.startswith("mock:")
            else provider_factory(config.judge_profile),
            config.judge_profile,
        )
        self.learner = (
            provider_factory(config.learner_profile)
            if config.learner_profile and not config.learner_profile.startswith("mock:")
            else None
        )

    # ------------------------------------------------------------------ utils

    def _write(self, record: dict) -> None:
        self.records[record["key"]] = record
        with self.results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.spent_usd += (
            float(record.get("cost_usd") or 0)
            + float(record.get("judge_cost_usd") or 0)
            + float(record.get("simulation_cost_usd") or 0)
        )

    def _check_budget(self) -> None:
        if self.config.max_cost_usd is not None and self.spent_usd >= self.config.max_cost_usd:
            raise BudgetExceeded(
                f"Stopped at ${self.spent_usd:.4f}, budget ${self.config.max_cost_usd:.4f}"
            )

    def _call(self, method: str, path: str, **kwargs) -> Any:
        for attempt in range(self.config.max_http_retries + 1):
            response = getattr(self.client, method)(path, **kwargs)
            if response.status_code < 400:
                return response.json()
            if response.status_code in RETRYABLE_STATUS and attempt < self.config.max_http_retries:
                delay = float(response.headers.get("Retry-After") or 2 ** (attempt + 1))
                time.sleep(min(delay, 60))
                continue
            raise RuntimeError(f"{method.upper()} {path} -> {response.status_code}: "
                               f"{response.text[:300]}")
        raise RuntimeError(f"{method.upper()} {path} exhausted retries")

    def _result_cost(self, result: ProviderResult | None) -> float:
        if result is None:
            return 0.0
        cost, _ = price(
            result.provider,
            result.model,
            result.input_tokens,
            result.output_tokens,
            self.config.price_overrides,
        )
        return cost

    def _usage(self, *, project_id: str | None = None, session_id: str | None = None) -> dict:
        from ..models import UsageEvent

        with self.session_factory() as db:
            query = select(UsageEvent)
            if session_id:
                query = query.where(UsageEvent.session_id == session_id)
            else:
                query = query.where(
                    UsageEvent.project_id == project_id, UsageEvent.session_id.is_(None)
                )
            rows = db.scalars(query).all()
        cost = 0.0
        unpriced = set()
        for row in rows:
            row_cost, priced = price(
                row.provider,
                row.model,
                row.input_tokens,
                row.output_tokens,
                self.config.price_overrides,
            )
            cost += row_cost
            if not priced:
                unpriced.add(f"{row.provider}:{row.model}")
        return {
            "cost_usd": round(cost, 8),
            "input_tokens": sum(row.input_tokens for row in rows),
            "output_tokens": sum(row.output_tokens for row in rows),
            "model_calls": len(rows),
            "unpriced_models": sorted(unpriced),
        }

    # ------------------------------------------------------------- blueprint

    def blueprint(self, material: Material, planner: str) -> dict:
        key = f"bp|{material.id}|{planner}"
        existing = self.records.get(key)
        if existing and not existing.get("error"):
            return existing
        self._check_budget()
        record: dict[str, Any] = {
            "kind": "blueprint",
            "key": key,
            "material_id": material.id,
            "domain": material.domain,
            "language": material.language,
            "planner": planner,
        }
        started = time.monotonic()
        try:
            project = self._call(
                "post",
                "/api/projects",
                json={
                    "name": f"quality-lab {material.id}"[:200],
                    "domain": "quality_lab",
                    "language": material.language,
                    "data_classification": "public",
                },
            )
            document = self._call(
                "post",
                f"/api/projects/{project['id']}/documents",
                files={
                    "file": (f"{material.id}.md", material.text.encode("utf-8"), "text/markdown")
                },
            )
            blueprint = self._call(
                "post",
                f"/api/projects/{project['id']}/blueprints",
                json={"document_id": document["id"], "profile": planner},
            )
            questions = blueprint["data"].get("questions") or []
            record.update(
                {
                    "project_id": project["id"],
                    "blueprint_id": blueprint["id"],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "questions": [
                        {
                            key_name: question.get(key_name)
                            for key_name in (
                                "id",
                                "text",
                                "type",
                                "difficulty",
                                "expected_points",
                                "followups",
                                "source_excerpt",
                            )
                        }
                        for question in questions
                    ],
                    **self._usage(project_id=project["id"]),
                }
            )
            ratings, judge_result = self.judge.rate_questions(material.text, questions)
            record["ratings"] = ratings
            record["judge_cost_usd"] = round(self._result_cost(judge_result), 8)
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - record and continue
            record["error"] = f"{type(exc).__name__}: {exc}"[:500]
        self._write(record)
        return record

    # --------------------------------------------------------------- session

    def session(
        self,
        material: Material,
        blueprint_record: dict,
        analyzer: str,
        persona_id: str,
        repeat: int,
        distractor: Material,
    ) -> dict:
        planner = blueprint_record["planner"]
        key = f"s|{material.id}|{planner}|{analyzer}|{persona_id}|{repeat}"
        existing = self.records.get(key)
        if existing and not existing.get("error"):
            return existing
        self._check_budget()
        persona = PERSONAS[persona_id]
        record: dict[str, Any] = {
            "kind": "session",
            "key": key,
            "material_id": material.id,
            "domain": material.domain,
            "planner": planner,
            "analyzer": analyzer,
            "persona": persona_id,
            "tier": persona.tier,
            "repeat": repeat,
            "exchanges": [],
        }
        simulation_cost = 0.0
        judge_cost = 0.0
        try:
            if blueprint_record.get("error"):
                raise RuntimeError("blueprint unavailable")
            questions = {
                str(question["id"]): question for question in blueprint_record["questions"]
            }
            ordered = blueprint_record["questions"]
            created = self._call(
                "post",
                "/api/sessions",
                json={
                    "project_id": blueprint_record["project_id"],
                    "blueprint_id": blueprint_record["blueprint_id"],
                    "profile": analyzer,
                    "question_limit": self.config.question_limit,
                    "max_followups_per_question": self.config.max_followups,
                },
            )
            session_id = created["id"]
            record["session_id"] = session_id
            started = self._call("post", f"/api/sessions/{session_id}/start")
            examiner_message = started["turn"]["content"]
            attempts: dict[str, int] = {}
            safety = self.config.question_limit * (self.config.max_followups + 2) + 2
            completed = False
            for _ in range(safety):
                state = self._call("get", f"/api/sessions/{session_id}")
                question = ordered[int(state["current_question_index"])]
                question_id = str(question["id"])
                attempt = attempts.get(question_id, 0)
                if self.learner and persona_id not in RULE_ONLY_PERSONAS:
                    answer, result = llm_answer(
                        self.learner,
                        persona_id,
                        question=question,
                        examiner_message=examiner_message,
                        material_text=material.text,
                        language=material.language,
                        distractor_text=distractor.text,
                    )
                    simulation_cost += self._result_cost(result)
                else:
                    answer = rule_based_answer(
                        persona_id,
                        question=question,
                        language=material.language,
                        turn_index=attempt,
                        distractor_text=distractor.text,
                    )
                began = time.monotonic()
                response = self._call(
                    "post",
                    f"/api/sessions/{session_id}/answers",
                    json={"answer": answer},
                )
                latency = int((time.monotonic() - began) * 1000)
                evaluation = response.get("evaluation") or {}
                decision = response.get("decision") or {}
                next_message = response["turns"][1]["content"]
                exchange = {
                    "question_id": question_id,
                    "attempt": attempt,
                    "answer": answer,
                    "system_score": evaluation.get("score"),
                    "action": decision.get("action"),
                    "next_message": next_message,
                    "latency_ms": latency,
                }
                if attempt == 0 and _stable_fraction(key + question_id) < self.config.judge_fraction:
                    judged, result = self.judge.rate_exchange(
                        {
                            "material": material.text,
                            "question": question.get("text"),
                            "expected_points": questions[question_id].get("expected_points"),
                            "source_excerpt": question.get("source_excerpt"),
                            "answer": answer,
                            "system_score": evaluation.get("score"),
                            "system_next_message": next_message,
                        }
                    )
                    exchange["judge"] = judged
                    judge_cost += self._result_cost(result)
                record["exchanges"].append(exchange)
                attempts[question_id] = attempt + 1
                examiner_message = next_message
                if response.get("completed"):
                    completed = True
                    break
            record["completed"] = completed
            report = self._call("get", f"/api/sessions/{session_id}/report")
            record["report_overall_score"] = report.get("overall_score")
            record.update(self._usage(session_id=session_id))
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - record and continue
            record["error"] = f"{type(exc).__name__}: {exc}"[:500]
        record["judge_cost_usd"] = round(judge_cost, 8)
        record["simulation_cost_usd"] = round(simulation_cost, 8)
        self._write(record)
        return record

    # ------------------------------------------------------------------- run

    def run(self) -> dict:
        config = self.config
        materials = [
            material
            for material in config.materials
            if _shard_of(material.id, config.shard_count) == config.shard_index
        ]
        stopped = None
        try:
            for material in materials:
                position = config.materials.index(material)
                distractor = next(
                    (
                        other
                        for other in config.materials[position + 1 :] + config.materials
                        if other.domain != material.domain
                    ),
                    material,
                )
                for planner in config.planner_profiles:
                    blueprint_record = self.blueprint(material, planner)
                    self.log(
                        f"[blueprint] {material.id} {planner} "
                        f"{'ERROR ' + blueprint_record['error'] if blueprint_record.get('error') else 'ok'}"
                    )
                    for analyzer in config.analyzer_profiles:
                        for persona_id in config.personas:
                            for repeat in range(config.repeats):
                                session_record = self.session(
                                    material,
                                    blueprint_record,
                                    analyzer,
                                    persona_id,
                                    repeat,
                                    distractor,
                                )
                                if session_record.get("error"):
                                    self.log(
                                        f"[session] {session_record['key']} ERROR "
                                        f"{session_record['error'][:160]}"
                                    )
                    self.log(f"[progress] spent ${self.spent_usd:.4f}")
        except BudgetExceeded as exc:
            stopped = str(exc)
            self.log(f"[budget] {stopped}")
        return {
            "results_path": str(self.results_path),
            "records": len(self.records),
            "spent_usd": round(self.spent_usd, 6),
            "stopped": stopped,
        }


def load_results(paths: list[Path]) -> list[dict]:
    records: dict[str, dict] = {}
    for path in paths:
        files = sorted(path.glob("results*.jsonl")) if path.is_dir() else [path]
        for file in files:
            for line in file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    records[record["key"]] = record
    return list(records.values())
