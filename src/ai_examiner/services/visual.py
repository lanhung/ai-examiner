from __future__ import annotations

from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.base import AgentContext
from ..agents.visual import VisualEvidenceAgent
from ..config import Settings
from ..model_catalog import estimate_cost
from ..models import Document, EvidenceAsset, UsageEvent, VisualAnalysis
from ..providers.factory import build_provider
from .budget import assert_budget
from .prompts import prompt_contents
from .storage import StorageObjectMissing, materialize_resource


class VisualEvidenceService:
    def __init__(self, db: Session, settings: Settings, project_id: str):
        self.db = db
        self.settings = settings
        self.project_id = project_id

    def _record(self, agent: str, result) -> None:
        self.db.add(
            UsageEvent(
                project_id=self.project_id,
                agent=agent,
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost_usd=estimate_cost(
                    result.provider, result.model, result.input_tokens, result.output_tokens
                ),
            )
        )

    def analyze_asset(self, asset: EvidenceAsset, profile: str, language: str) -> VisualAnalysis:
        assert_budget(self.db, self.settings, self.project_id)
        provider = build_provider(self.settings, profile)
        agent = VisualEvidenceAgent(
            AgentContext(
                provider=provider,
                record_usage=self._record,
                prompt_overrides=prompt_contents(self.db),
            )
        )
        started = perf_counter()
        try:
            with materialize_resource(
                self.db,
                self.settings,
                organization_id=asset.organization_id,
                storage_object_id=asset.storage_object_id,
                legacy_path=asset.storage_path,
            ) as image_path:
                data = agent.analyze(
                    image_path=image_path,
                    page_number=asset.page_number,
                    label=asset.label,
                    nearby_text=asset.text,
                    language=language,
                )
        except StorageObjectMissing as exc:
            raise ValueError("Evidence asset has no readable image") from exc
        data["latency_ms"] = int((perf_counter() - started) * 1000)
        analysis = VisualAnalysis(
            project_id=self.project_id,
            document_id=asset.document_id,
            evidence_asset_id=asset.id,
            provider=provider.name,
            model=provider.image_model,
            prompt_version="visual_evidence:v1",
            data=data,
        )
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def analyze_document(
        self,
        document: Document,
        profile: str,
        language: str,
        max_pages: int,
    ) -> list[VisualAnalysis]:
        assets = self.db.scalars(
            select(EvidenceAsset)
            .where(EvidenceAsset.document_id == document.id, EvidenceAsset.kind == "page")
            .order_by(EvidenceAsset.page_number)
            .limit(max_pages)
        ).all()
        return [self.analyze_asset(asset, profile, language) for asset in assets]
