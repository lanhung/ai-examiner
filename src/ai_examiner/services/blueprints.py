from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents.orchestrator import ExamOrchestrator
from ..config import Settings
from ..models import Blueprint, Document, EvidenceAsset, Project
from .model_governance import governed_provider
from .session_templates import SessionTemplateService


@dataclass(frozen=True)
class PreparedBlueprint:
    data: dict[str, Any]
    grounding: dict[str, Any]
    provider: str
    model: str


class BlueprintGenerationService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def prepare(
        self,
        *,
        project: Project,
        document: Document,
        profile: str | None,
        mode: str,
        template_version_id: str | None,
        template_overrides: dict[str, Any],
    ) -> PreparedBlueprint:
        resolved_template = SessionTemplateService(self.db).resolve(
            project,
            mode=mode,
            template_version_id=template_version_id,
            template_overrides=template_overrides,
            request_overrides={},
        )
        provider = governed_provider(
            self.db,
            self.settings,
            profile,
            project_id=project.id,
        )
        data, grounding = ExamOrchestrator(
            self.db,
            provider,
            project_id=project.id,
        ).build_blueprint(
            document_text=document.content_text,
            filename=document.filename,
            language=project.language,
            template_contract=(
                resolved_template.snapshot if resolved_template else None
            ),
        )
        if resolved_template:
            data.setdefault("template_plan", {}).update(
                {
                    "template_version_id": resolved_template.template_version_id,
                    "fingerprint": resolved_template.fingerprint,
                    "compiler_version": resolved_template.compiler_version,
                    "resolution_source": resolved_template.resolution_source,
                }
            )
        self._attach_page_evidence(document, data)
        return PreparedBlueprint(
            data=data,
            grounding=grounding,
            provider=provider.name,
            model=provider.model,
        )

    def persist(
        self,
        *,
        project: Project,
        document: Document,
        prepared: PreparedBlueprint,
    ) -> Blueprint:
        version = (
            self.db.scalar(
                select(func.count(Blueprint.id)).where(
                    Blueprint.project_id == project.id
                )
            )
            or 0
        )
        blueprint = Blueprint(
            project_id=project.id,
            document_id=document.id,
            version=version + 1,
            data=prepared.data,
            provider=prepared.provider,
            model=prepared.model,
        )
        self.db.add(blueprint)
        self.db.commit()
        self.db.refresh(blueprint)
        return blueprint

    def _attach_page_evidence(
        self,
        document: Document,
        data: dict[str, Any],
    ) -> None:
        page_assets = {
            asset.page_number: asset
            for asset in self.db.scalars(
                select(EvidenceAsset).where(
                    EvidenceAsset.document_id == document.id,
                    EvidenceAsset.kind == "page",
                )
            ).all()
        }
        for question in data.get("questions") or []:
            page_number = int(question.get("source_page") or 1)
            page_asset = page_assets.get(page_number)
            question["evidence_asset_ids"] = [page_asset.id] if page_asset else []
            question["page_preview_url"] = (
                f"/api/evidence/{page_asset.id}/file" if page_asset else None
            )


def serialize_blueprint(
    blueprint: Blueprint,
    *,
    grounding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": blueprint.id,
        "version": blueprint.version,
        "provider": blueprint.provider,
        "model": blueprint.model,
        "grounding": grounding or blueprint.data.get("grounding_check") or {},
        "template_plan": blueprint.data.get("template_plan"),
        "data": blueprint.data,
    }
