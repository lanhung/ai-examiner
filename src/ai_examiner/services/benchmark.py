from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from statistics import mean
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from ..agents.analyzer import AnswerAnalyzer
from ..agents.base import AgentContext
from ..agents.planner import SessionPlanner
from ..config import Settings
from ..model_catalog import estimate_cost
from ..models import BenchmarkRun, Document, GoldenDataset, UsageEvent
from ..providers.base import ModelProvider, ProviderResult
from .budget import assert_budget
from .model_governance import governed_provider
from .prompts import prompt_contents


@dataclass
class BenchmarkCall:
    profile: str
    agent: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


def _tokens(text: str) -> set[str]:
    return set(
        re.findall(
            r"[a-zA-Z][a-zA-Z0-9_-]{2,}|[\u4e00-\u9fff]{2,6}",
            (text or "").lower(),
        )
    )


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _max_similarity(text: str, candidates: list[str]) -> float:
    return max((_similarity(text, item) for item in candidates), default=0.0)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _mean_or_zero(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _bootstrap_ci(values: list[float], samples: int = 400, seed: int = 17) -> list[float]:
    if not values:
        return [0.0, 0.0]
    if len(values) == 1:
        value = round(values[0], 3)
        return [value, value]
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        means.append(mean(draw))
    means.sort()
    lower = means[int(0.025 * (len(means) - 1))]
    upper = means[int(0.975 * (len(means) - 1))]
    return [round(lower, 3), round(upper, 3)]


class BenchmarkService:
    """Run Planner and Analyzer profiles against an AI-curated Golden Dataset."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        project_id: str,
        document: Document,
        dataset: GoldenDataset,
    ) -> None:
        self.db = db
        self.settings = settings
        self.project_id = project_id
        self.document = document
        self.dataset = dataset
        self.calls: list[BenchmarkCall] = []
        self._active_profile = ""

    def _record_usage(self, agent: str, result: ProviderResult) -> None:
        cost = estimate_cost(
            result.provider, result.model, result.input_tokens, result.output_tokens
        )
        self.db.add(
            UsageEvent(
                project_id=self.project_id,
                agent=f"benchmark_{agent}",
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost_usd=cost,
            )
        )
        self.calls.append(
            BenchmarkCall(
                profile=self._active_profile,
                agent=agent,
                latency_ms=0,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost_usd=cost,
            )
        )

    def _context(self, provider: ModelProvider, profile: str) -> AgentContext:
        self._active_profile = profile
        return AgentContext(
            provider=provider,
            record_usage=self._record_usage,
            prompt_overrides=prompt_contents(self.db),
        )

    def _timed(self, fn, *args, **kwargs):
        before = len(self.calls)
        started = perf_counter()
        value = fn(*args, **kwargs)
        latency = int((perf_counter() - started) * 1000)
        if len(self.calls) > before:
            self.calls[-1].latency_ms = latency
        return value

    def _planner_metrics(self, plan: dict[str, Any], golden_cases: list[dict]) -> dict:
        questions = plan.get("questions") or []
        golden_questions = [str(case.get("question", "")) for case in golden_cases]
        golden_types = {str(case.get("type", "unknown")) for case in golden_cases}
        document = _normalize(self.document.content_text)

        similarities = [
            _max_similarity(str(question.get("text", "")), golden_questions)
            for question in questions
        ]
        grounded = [
            1.0
            if _normalize(str(question.get("source_excerpt", "")))
            and _normalize(str(question.get("source_excerpt", ""))) in document
            else 0.0
            for question in questions
        ]
        generated_types = {str(question.get("type", "unknown")) for question in questions}
        format_complete = [
            1.0
            if question.get("text")
            and question.get("expected_points")
            and question.get("followups")
            and question.get("source_excerpt")
            else 0.0
            for question in questions
        ]
        recall_threshold = 0.12
        golden_recalled = [
            1.0
            if _max_similarity(golden_question, [q.get("text", "") for q in questions])
            >= recall_threshold
            else 0.0
            for golden_question in golden_questions
        ]
        coverage = len(generated_types & golden_types) / max(1, len(golden_types))
        score = 100 * (
            0.25 * _mean_or_zero(grounded)
            + 0.20 * _mean_or_zero(format_complete)
            + 0.20 * coverage
            + 0.20 * _mean_or_zero(golden_recalled)
            + 0.15 * min(1.0, _mean_or_zero(similarities) / 0.25)
        )
        return {
            "question_count": len(questions),
            "grounded_rate": round(_mean_or_zero(grounded), 3),
            "format_completeness": round(_mean_or_zero(format_complete), 3),
            "type_coverage": round(coverage, 3),
            "golden_question_recall": round(_mean_or_zero(golden_recalled), 3),
            "mean_question_similarity": round(_mean_or_zero(similarities), 3),
            "score": round(score, 2),
        }

    def _analyzer_metrics(
        self,
        analyzer: AnswerAnalyzer,
        golden_cases: list[dict],
        case_limit: int,
    ) -> tuple[dict, list[dict]]:
        records: list[dict] = []
        label_hits: list[float] = []
        coverage_errors: list[float] = []
        error_detection: list[float] = []

        for case in golden_cases[:case_limit]:
            question = {
                "id": case.get("id"),
                "text": case.get("question"),
                "type": case.get("type"),
                "difficulty": case.get("difficulty"),
                "expected_points": case.get("required_points") or [],
                "followups": case.get("followups") or [],
                "source_excerpt": case.get("source_excerpt", ""),
                "source_page": case.get("source_page", 1),
            }
            for variant in case.get("synthetic_answers") or []:
                predicted = self._timed(
                    analyzer.analyze,
                    question=question,
                    answer=str(variant.get("answer", "")),
                    history=[],
                )
                expected_label = str(variant.get("expected_correctness", ""))
                actual_label = str(predicted.get("correctness", ""))
                label_hit = float(actual_label == expected_label)
                expected_coverage = float(variant.get("expected_coverage", 0.0))
                actual_coverage = float(predicted.get("coverage", 0.0))
                coverage_error = abs(actual_coverage - expected_coverage)
                expected_errors = [str(x) for x in variant.get("expected_errors") or []]
                predicted_errors = [str(x) for x in predicted.get("errors") or []]
                if expected_errors:
                    detected = max(
                        (
                            _max_similarity(expected, predicted_errors)
                            for expected in expected_errors
                        ),
                        default=0.0,
                    )
                    error_hit = float(detected >= 0.08)
                    error_detection.append(error_hit)
                else:
                    error_hit = None
                label_hits.append(label_hit)
                coverage_errors.append(coverage_error)
                records.append(
                    {
                        "case_id": case.get("id"),
                        "variant": variant.get("variant"),
                        "expected_label": expected_label,
                        "predicted_label": actual_label,
                        "label_correct": bool(label_hit),
                        "expected_coverage": expected_coverage,
                        "predicted_coverage": actual_coverage,
                        "coverage_absolute_error": round(coverage_error, 3),
                        "expected_error_detected": error_hit,
                        "predicted_errors": predicted_errors,
                    }
                )

        label_accuracy = _mean_or_zero(label_hits)
        coverage_mae = _mean_or_zero(coverage_errors)
        error_recall = _mean_or_zero(error_detection) if error_detection else 1.0
        labels = sorted(
            {record["expected_label"] for record in records}
            | {record["predicted_label"] for record in records}
        )
        confusion = {
            expected: {
                predicted: sum(
                    1
                    for record in records
                    if record["expected_label"] == expected
                    and record["predicted_label"] == predicted
                )
                for predicted in labels
            }
            for expected in labels
        }
        by_variant = {}
        for variant in sorted({str(record["variant"]) for record in records}):
            subset = [record for record in records if record["variant"] == variant]
            by_variant[variant] = {
                "sample_count": len(subset),
                "label_accuracy": round(
                    _mean_or_zero([float(item["label_correct"]) for item in subset]), 3
                ),
                "coverage_mae": round(
                    _mean_or_zero([float(item["coverage_absolute_error"]) for item in subset]), 3
                ),
            }
        score = 100 * (
            0.55 * label_accuracy
            + 0.25 * max(0.0, 1.0 - coverage_mae)
            + 0.20 * error_recall
        )
        return (
            {
                "sample_count": len(records),
                "label_accuracy": round(label_accuracy, 3),
                "coverage_mae": round(coverage_mae, 3),
                "misconception_detection_rate": round(error_recall, 3),
                "label_accuracy_95ci": _bootstrap_ci(label_hits),
                "confusion_matrix": confusion,
                "by_variant": by_variant,
                "score": round(score, 2),
            },
            records,
        )

    def run(
        self,
        *,
        profiles: list[str],
        case_limit: int,
        run_planner: bool,
        run_analyzer: bool,
        language: str,
    ) -> BenchmarkRun:
        golden_cases = self.dataset.data.get("cases") or []
        if not golden_cases:
            raise ValueError("Golden Dataset contains no cases")
        results: list[dict] = []

        for profile in profiles:
            assert_budget(self.db, self.settings, self.project_id)
            calls_before = len(self.calls)
            provider = governed_provider(
                self.db,
                self.settings,
                profile,
                project_id=self.project_id,
            )
            profile_result: dict[str, Any] = {"profile": profile}

            if run_planner:
                planner = SessionPlanner(self._context(provider, profile))
                plan = self._timed(
                    planner.plan,
                    document_text=self.document.content_text,
                    filename=self.document.filename,
                    language=language,
                )
                profile_result["planner"] = self._planner_metrics(plan, golden_cases)

            if run_analyzer:
                analyzer = AnswerAnalyzer(self._context(provider, profile))
                analyzer_metrics, analyzer_records = self._analyzer_metrics(
                    analyzer, golden_cases, case_limit
                )
                profile_result["analyzer"] = analyzer_metrics
                profile_result["analyzer_records"] = analyzer_records

            profile_calls = self.calls[calls_before:]
            profile_result["operations"] = len(profile_calls)
            profile_result["latency_ms"] = sum(call.latency_ms for call in profile_calls)
            profile_result["input_tokens"] = sum(call.input_tokens for call in profile_calls)
            profile_result["output_tokens"] = sum(call.output_tokens for call in profile_calls)
            profile_result["estimated_cost_usd"] = round(
                sum(call.estimated_cost_usd for call in profile_calls), 6
            )
            component_scores = [
                float(profile_result[key]["score"])
                for key in ("planner", "analyzer")
                if key in profile_result
            ]
            profile_result["quality_score"] = round(_mean_or_zero(component_scores), 2)
            results.append(profile_result)

        ranked = sorted(
            results,
            key=lambda item: (
                -float(item.get("quality_score", 0)),
                float(item.get("estimated_cost_usd", math.inf)),
                int(item.get("latency_ms", 0)),
            ),
        )
        for rank, item in enumerate(ranked, start=1):
            item["rank"] = rank

        run = BenchmarkRun(
            project_id=self.project_id,
            document_id=self.document.id,
            golden_dataset_id=self.dataset.id,
            status="completed",
            profiles=profiles,
            config={
                "case_limit": case_limit,
                "run_planner": run_planner,
                "run_analyzer": run_analyzer,
            },
            results=ranked,
            summary={
                "winner": ranked[0]["profile"] if ranked else None,
                "profile_count": len(ranked),
                "total_operations": len(self.calls),
                "total_latency_ms": sum(call.latency_ms for call in self.calls),
                "total_estimated_cost_usd": round(
                    sum(call.estimated_cost_usd for call in self.calls), 6
                ),
                "ranking_rule": "quality desc, then cost asc, then latency asc",
            },
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run
