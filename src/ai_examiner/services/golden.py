from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents.base import AgentContext
from ..agents.golden import (
    AnnotationCritic,
    ConsensusSynthesizer,
    GoldenAnnotator,
    SyntheticAnswerGenerator,
    cases_from_candidates,
)
from ..config import Settings
from ..model_catalog import estimate_cost
from ..models import Document, EvidenceAsset, GoldenDataset, UsageEvent
from ..providers.base import ModelProvider, ProviderResult
from ..providers.factory import build_provider
from ..providers.mock import MockProvider
from .budget import assert_budget
from .prompts import prompt_contents, prompt_manifest


@dataclass
class CallRecord:
    profile: str
    agent: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def validate_dataset(data: dict, document_text: str) -> dict:
    cases = data.get("cases") or []
    normalized_document = _normalize(document_text)
    issues: list[str] = []
    grounded = 0
    complete = 0
    unique_questions: set[str] = set()
    type_counts: dict[str, int] = {}

    for case in cases:
        question = _normalize(case.get("question", ""))
        excerpt = _normalize(case.get("source_excerpt", ""))
        if excerpt and excerpt in normalized_document:
            grounded += 1
        else:
            issues.append(f"{case.get('id', '?')}: source excerpt not found verbatim")
        required = case.get("required_points") or []
        followups = case.get("followups") or []
        errors = case.get("common_errors") or []
        rubric = case.get("scoring_rubric") or {}
        if (
            question
            and case.get("ideal_answer")
            and len(required) >= 2
            and len(followups) >= 1
            and len(errors) >= 1
            and all(rubric.get(x) for x in ("excellent", "acceptable", "insufficient"))
        ):
            complete += 1
        else:
            issues.append(f"{case.get('id', '?')}: incomplete annotation fields")
        if question in unique_questions:
            issues.append(f"{case.get('id', '?')}: duplicate question")
        unique_questions.add(question)
        case_type = str(case.get("type", "unknown"))
        type_counts[case_type] = type_counts.get(case_type, 0) + 1

    quality_values = []
    for case in cases:
        scores = case.get("quality_scores") or {}
        numeric = [float(v) for v in scores.values() if isinstance(v, (int, float))]
        if numeric:
            quality_values.append(mean(numeric))

    count = len(cases)
    return {
        "case_count": count,
        "grounded_rate": round(grounded / count, 3) if count else 0.0,
        "annotation_completeness": round(complete / count, 3) if count else 0.0,
        "unique_question_rate": round(len(unique_questions) / count, 3) if count else 0.0,
        "type_coverage": len(type_counts),
        "type_distribution": type_counts,
        "mean_ai_panel_score": round(mean(quality_values), 3) if quality_values else None,
        "issues": issues,
        "release_ready": bool(count >= 4 and grounded == count and complete == count),
    }


class GoldenDatasetService:
    def __init__(self, db: Session, settings: Settings, project_id: str, document: Document):
        self.db = db
        self.settings = settings
        self.project_id = project_id
        self.document = document
        self.call_records: list[CallRecord] = []
        self._active_profile = ""

    def _record_usage(self, agent: str, result: ProviderResult) -> None:
        cost = estimate_cost(
            result.provider, result.model, result.input_tokens, result.output_tokens
        )
        self.db.add(
            UsageEvent(
                project_id=self.project_id,
                agent=agent,
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost_usd=cost,
            )
        )
        self.call_records.append(
            CallRecord(
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
        started = perf_counter()
        result = fn(*args, **kwargs)
        latency = int((perf_counter() - started) * 1000)
        if self.call_records:
            self.call_records[-1].latency_ms = latency
        return result

    def generate(
        self,
        *,
        profiles: list[str],
        consensus_profile: str,
        question_count: int,
        language: str,
    ) -> GoldenDataset:
        if not profiles:
            profiles = ["mock:heuristic-v2"]
        candidates: list[dict] = []
        critiques: list[dict] = []

        for profile in profiles:
            assert_budget(self.db, self.settings, self.project_id)
            provider = build_provider(self.settings, profile)
            annotator = GoldenAnnotator(self._context(provider, profile))
            try:
                candidate = self._timed(
                    annotator.generate,
                    document_text=self.document.content_text,
                    filename=self.document.filename,
                    language=language,
                    question_count=question_count,
                )
            except ValueError as exc:
                if "returned no cases" not in str(exc):
                    raise
                fallback_profile = "mock:heuristic-v2"
                fallback = GoldenAnnotator(self._context(MockProvider(), fallback_profile))
                candidate = self._timed(
                    fallback.generate,
                    document_text=self.document.content_text,
                    filename=self.document.filename,
                    language=language,
                    question_count=question_count,
                )
                candidate["fallback_from_profile"] = profile
                candidate["fallback_reason"] = str(exc)
            candidate["generator_profile"] = profile
            candidates.append(candidate)

        # Cross-review each candidate with the next available model. With one model, self-critique
        # is still useful but is explicitly marked in provenance.
        for index, candidate in enumerate(candidates):
            critic_profile = profiles[(index + 1) % len(profiles)]
            provider = build_provider(self.settings, critic_profile)
            critic = AnnotationCritic(self._context(provider, critic_profile))
            critique = self._timed(
                critic.review,
                document_text=self.document.content_text,
                candidate=candidate,
            )
            critique["candidate_profile"] = candidate["generator_profile"]
            critique["critic_profile"] = critic_profile
            critiques.append(critique)

        assert_budget(self.db, self.settings, self.project_id)
        consensus_provider = build_provider(self.settings, consensus_profile)
        consensus = ConsensusSynthesizer(
            self._context(consensus_provider, consensus_profile)
        )
        data = self._timed(
            consensus.synthesize,
            document_text=self.document.content_text,
            candidates=candidates,
            critiques=critiques,
            question_count=question_count,
        )
        if not data.get("cases"):
            data = cases_from_candidates(candidates, question_count)

        answer_generator = SyntheticAnswerGenerator(
            self._context(consensus_provider, consensus_profile)
        )
        synthetic = self._timed(answer_generator.generate, cases=data.get("cases", []))
        variants_by_case = {
            item.get("case_id"): item.get("variants", [])
            for item in synthetic.get("answers", [])
        }
        page_assets = {
            asset.page_number: asset
            for asset in self.db.scalars(
                select(EvidenceAsset).where(
                    EvidenceAsset.document_id == self.document.id,
                    EvidenceAsset.kind == "page",
                )
            ).all()
        }
        text_assets = self.db.scalars(
            select(EvidenceAsset).where(
                EvidenceAsset.document_id == self.document.id,
                EvidenceAsset.kind != "page",
            )
        ).all()
        for case in data.get("cases", []):
            case["synthetic_answers"] = variants_by_case.get(case.get("id"), [])
            source_page = int(case.get("source_page") or 1)
            excerpt = _normalize(str(case.get("source_excerpt") or ""))
            linked = []
            page_asset = page_assets.get(source_page)
            if page_asset:
                linked.append(page_asset.id)
            for asset in text_assets:
                if asset.page_number != source_page:
                    continue
                normalized_asset = _normalize(asset.text)
                if excerpt and (excerpt in normalized_asset or normalized_asset in excerpt):
                    linked.append(asset.id)
                    break
            case["evidence_asset_ids"] = linked
            case["page_preview_url"] = (
                f"/api/evidence/{page_asset.id}/file" if page_asset else None
            )

        data["provenance"] = {
            "candidate_profiles": profiles,
            "consensus_profile": consensus_profile,
            "candidate_count": len(candidates),
            "cross_reviewed": True,
            "prompt_versions": prompt_manifest(self.db),
            "source_document": {
                "id": self.document.id,
                "filename": self.document.filename,
                "page_count": len(self.document.page_map or []),
            },
            "candidate_summaries": [
                {
                    "profile": c.get("generator_profile"),
                    "case_count": len(c.get("cases") or []),
                }
                for c in candidates
            ],
        }
        quality = validate_dataset(data, self.document.content_text)
        quality["generation_calls"] = [record.__dict__ for record in self.call_records]
        quality["total_estimated_cost_usd"] = round(
            sum(x.estimated_cost_usd for x in self.call_records), 6
        )
        quality["total_latency_ms"] = sum(x.latency_ms for x in self.call_records)

        version = (
            self.db.scalar(
                select(func.count(GoldenDataset.id)).where(
                    GoldenDataset.project_id == self.project_id
                )
            )
            or 0
        ) + 1
        dataset = GoldenDataset(
            project_id=self.project_id,
            document_id=self.document.id,
            name=f"{self.document.filename} Golden Dataset",
            version=version,
            status="ready" if quality["release_ready"] else "needs_review",
            generator_profiles=profiles,
            consensus_profile=consensus_profile,
            data=data,
            quality_metrics=quality,
        )
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset
