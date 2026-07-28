from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ExamSession,
    Project,
    ProjectTemplateBinding,
    ScenarioTemplate,
    ScenarioTemplateVersion,
)
from ..template_engine.compiler import (
    TemplateCompiler,
    TemplateOverrideError,
    TemplateValidationError,
    canonical_json,
)
from .templates import TemplateLifecycleError
from .tenancy import tenant_organization_or_legacy

LEGACY_TEMPLATE_SLUGS = {
    "defense": "academic.thesis_defense",
}
SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)


@dataclass(frozen=True)
class ResolvedSessionTemplate:
    template_version_id: str
    snapshot: dict[str, Any]
    fingerprint: str
    compiler_version: str
    overrides: dict[str, Any]
    resolution_source: str
    effective_mode: str

    @property
    def legacy(self) -> dict[str, Any]:
        return self.snapshot["legacy"]


def _now() -> datetime:
    return datetime.now(UTC)


def _semver_key(value: str) -> tuple[int, int, int, int, str]:
    match = SEMVER_PATTERN.fullmatch(value)
    if not match:
        return (0, 0, 0, 0, value)
    prerelease = match.group("prerelease")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if prerelease is None else 0,
        prerelease or "",
    )


def serialize_project_template_binding(
    binding: ProjectTemplateBinding | None,
) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "id": binding.id,
        "project_id": binding.project_id,
        "template_version_id": binding.template_version_id,
        "default_overrides": binding.default_overrides_json,
        "created_at": binding.created_at.isoformat(),
        "superseded_at": (
            binding.superseded_at.isoformat() if binding.superseded_at else None
        ),
    }


class SessionTemplateService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.compiler = TemplateCompiler()

    def active_binding(self, project_id: str) -> ProjectTemplateBinding | None:
        return self.db.scalar(
            select(ProjectTemplateBinding)
            .where(
                ProjectTemplateBinding.project_id == project_id,
                ProjectTemplateBinding.superseded_at.is_(None),
            )
            .order_by(ProjectTemplateBinding.created_at.desc())
        )

    def bind_project(
        self,
        project: Project,
        version: ScenarioTemplateVersion,
        *,
        default_overrides: dict[str, Any] | None = None,
    ) -> ProjectTemplateBinding:
        self._require_selectable(version)
        overrides = copy.deepcopy(default_overrides or {})
        self._compile(version, overrides)
        current = self.active_binding(project.id)
        if current:
            current.superseded_at = _now()
        binding = ProjectTemplateBinding(
            organization_id=project.organization_id
            or tenant_organization_or_legacy(self.db),
            project_id=project.id,
            template_version_id=version.id,
            default_overrides_json=overrides,
        )
        self.db.add(binding)
        self.db.commit()
        self.db.refresh(binding)
        return binding

    def clear_project_binding(self, project_id: str) -> ProjectTemplateBinding | None:
        current = self.active_binding(project_id)
        if current is None:
            return None
        current.superseded_at = _now()
        self.db.commit()
        self.db.refresh(current)
        return current

    def resolve(
        self,
        project: Project,
        *,
        mode: str,
        template_version_id: str | None,
        template_overrides: dict[str, Any] | None,
        request_overrides: dict[str, Any] | None,
    ) -> ResolvedSessionTemplate | None:
        version: ScenarioTemplateVersion | None = None
        defaults: dict[str, Any] = {}
        resolution_source = "legacy"
        if template_version_id:
            version = self.db.get(ScenarioTemplateVersion, template_version_id)
            if version is None:
                raise TemplateLifecycleError(
                    "TEMPLATE_VERSION_NOT_FOUND",
                    "Selected template version was not found",
                    status_code=404,
                )
            resolution_source = "explicit"
        else:
            binding = self.active_binding(project.id)
            if binding:
                version = self.db.get(
                    ScenarioTemplateVersion,
                    binding.template_version_id,
                )
                defaults = copy.deepcopy(binding.default_overrides_json or {})
                resolution_source = "project_default"
            else:
                version = self._legacy_version(mode)
                if version is None:
                    return None

        self._require_selectable(version)
        compatibility = (version.source_json or {}).get("compatibility") or {}
        effective_mode = str(compatibility.get("mode") or mode)
        if compatibility.get("mode") and compatibility["mode"] != mode:
            raise TemplateLifecycleError(
                "TEMPLATE_MODE_CONFLICT",
                f"Template mode {compatibility['mode']} conflicts with request mode {mode}",
            )
        overrides = {
            **defaults,
            **copy.deepcopy(template_overrides or {}),
            **copy.deepcopy(request_overrides or {}),
        }
        compiled = self._compile(version, overrides)
        return ResolvedSessionTemplate(
            template_version_id=version.id,
            snapshot=copy.deepcopy(compiled.compiled),
            fingerprint=compiled.fingerprint,
            compiler_version=compiled.compiler_version,
            overrides=overrides,
            resolution_source=resolution_source,
            effective_mode=effective_mode,
        )

    def inspect_session(self, session: ExamSession) -> dict[str, Any]:
        if not session.template_version_id:
            return {
                "bound": False,
                "legacy_session": True,
                "template_version_id": None,
                "fingerprint": None,
                "integrity": "not_applicable",
            }
        version = self.db.get(
            ScenarioTemplateVersion,
            session.template_version_id,
        )
        if version is None or not session.template_snapshot_json:
            return {
                "bound": True,
                "legacy_session": False,
                "template_version_id": session.template_version_id,
                "fingerprint": session.template_fingerprint,
                "integrity": "missing_artifact",
            }
        payload = {
            "compiler_version": session.template_compiler_version,
            "schema_version": version.schema_version,
            "compiled": session.template_snapshot_json,
        }
        actual = "sha256:" + hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        return {
            "bound": True,
            "legacy_session": False,
            "template_id": version.template_id,
            "template_version_id": version.id,
            "semantic_version": version.semantic_version,
            "fingerprint": session.template_fingerprint,
            "compiler_version": session.template_compiler_version,
            "overrides": session.template_overrides_json or {},
            "resolution_source": session.config.get("template_resolution_source"),
            "integrity": (
                "verified"
                if actual == session.template_fingerprint
                else "fingerprint_mismatch"
            ),
            "snapshot": session.template_snapshot_json,
        }

    def _legacy_version(self, mode: str) -> ScenarioTemplateVersion | None:
        slug = LEGACY_TEMPLATE_SLUGS.get(mode)
        if not slug:
            return None
        template = self.db.scalar(
            select(ScenarioTemplate).where(
                ScenarioTemplate.slug == slug,
                ScenarioTemplate.status == "active",
            )
        )
        if template is None:
            return None
        versions = self.db.scalars(
            select(ScenarioTemplateVersion).where(
                ScenarioTemplateVersion.template_id == template.id,
                ScenarioTemplateVersion.status == "published",
            )
        ).all()
        if not versions:
            return None
        return max(
            versions,
            key=lambda item: _semver_key(item.semantic_version),
        )

    @staticmethod
    def _require_selectable(version: ScenarioTemplateVersion) -> None:
        if version.template.status != "active":
            raise TemplateLifecycleError(
                "TEMPLATE_NOT_ACTIVE",
                "Only active templates can start new sessions",
            )
        if version.status != "published":
            raise TemplateLifecycleError(
                "TEMPLATE_VERSION_NOT_SELECTABLE",
                "Only published template versions can start new sessions",
            )
        if not version.compiled_json or not version.fingerprint:
            raise TemplateLifecycleError(
                "TEMPLATE_PUBLISHED_ARTIFACT_MISSING",
                "Published template version has no compiled artifact",
            )

    def _compile(
        self,
        version: ScenarioTemplateVersion,
        overrides: dict[str, Any],
    ):
        try:
            return self.compiler.compile(
                version.source_json,
                overrides=overrides,
            )
        except TemplateOverrideError as exc:
            issue = exc.issues[0]
            raise TemplateLifecycleError(
                issue.code,
                issue.message,
                status_code=422,
            ) from exc
        except TemplateValidationError as exc:
            issue = exc.issues[0]
            raise TemplateLifecycleError(
                issue.code,
                issue.message,
                status_code=422,
            ) from exc


__all__ = [
    "ResolvedSessionTemplate",
    "SessionTemplateService",
    "serialize_project_template_binding",
]
