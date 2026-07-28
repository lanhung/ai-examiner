from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ScenarioTemplate,
    ScenarioTemplateVersion,
    TemplateValidationRun,
)
from ..template_engine.catalog import BUILTIN_TEMPLATE_FILES
from ..template_engine.compiler import (
    TEMPLATE_COMPILER_VERSION,
    TemplateCompiler,
    canonical_json,
)
from ..template_engine.parser import TemplateParseError, parse_template_document
from ..template_engine.registries import CAPABILITIES
from ..template_engine.validator import (
    TEMPLATE_VALIDATOR_VERSION,
    TemplateValidationResult,
    validate_template,
)
from ..templates.builtin import load_builtin_template
from .tenancy import tenant_organization_or_legacy

TEMPLATE_VERSION_STATES = {"draft", "candidate", "published", "deprecated"}
TEMPLATE_TRANSITIONS = {
    "draft": {"candidate"},
    "candidate": {"draft", "published"},
    "published": {"deprecated"},
    "deprecated": set(),
}


class TemplateLifecycleError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _issues(result: TemplateValidationResult) -> list[dict[str, Any]]:
    return [issue.model_dump(mode="json") for issue in result.issues]


def _bounded_source(source: dict[str, Any]) -> dict[str, Any]:
    try:
        return parse_template_document(canonical_json(source))
    except (TemplateParseError, TypeError, ValueError) as exc:
        raise TemplateLifecycleError(
            "TEMPLATE_SOURCE_INVALID",
            f"Template source is not safe or bounded: {exc}",
            status_code=422,
        ) from exc


def serialize_validation_run(run: TemplateValidationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "template_version_id": run.template_version_id,
        "validator_version": run.validator_version,
        "status": run.status,
        "issues": run.issues_json,
        "capability_snapshot": run.capability_snapshot_json,
        "created_at": run.created_at.isoformat(),
    }


def latest_validation_run(
    db: Session,
    version_id: str,
) -> TemplateValidationRun | None:
    return db.scalar(
        select(TemplateValidationRun)
        .where(TemplateValidationRun.template_version_id == version_id)
        .order_by(TemplateValidationRun.created_at.desc())
    )


def serialize_template_version(
    db: Session,
    version: ScenarioTemplateVersion,
    *,
    include_source: bool = True,
    include_compiled: bool = False,
) -> dict[str, Any]:
    validation = latest_validation_run(db, version.id)
    payload: dict[str, Any] = {
        "id": version.id,
        "template_id": version.template_id,
        "semantic_version": version.semantic_version,
        "schema_version": version.schema_version,
        "status": version.status,
        "compiler_version": version.compiler_version,
        "fingerprint": version.fingerprint,
        "evaluation_summary": version.evaluation_summary_json,
        "created_from_version_id": version.created_from_version_id,
        "created_at": version.created_at.isoformat(),
        "published_at": (
            version.published_at.isoformat() if version.published_at else None
        ),
        "latest_validation": (
            serialize_validation_run(validation) if validation else None
        ),
    }
    if include_source:
        payload["source"] = version.source_json
    if include_compiled:
        payload["compiled"] = version.compiled_json
    return payload


def serialize_template(
    db: Session,
    template: ScenarioTemplate,
    *,
    include_source: bool = False,
) -> dict[str, Any]:
    versions = db.scalars(
        select(ScenarioTemplateVersion)
        .where(ScenarioTemplateVersion.template_id == template.id)
        .order_by(ScenarioTemplateVersion.created_at.desc())
    ).all()
    return {
        "id": template.id,
        "slug": template.slug,
        "category": template.category,
        "owner_scope": template.owner_scope,
        "status": template.status,
        "created_at": template.created_at.isoformat(),
        "versions": [
            serialize_template_version(
                db,
                version,
                include_source=include_source,
                include_compiled=False,
            )
            for version in versions
        ],
    }


class TemplateLifecycleService:
    def __init__(
        self,
        db: Session,
        *,
        deployment_capabilities: set[str] | None = None,
    ) -> None:
        self.db = db
        self.deployment_capabilities = set(deployment_capabilities or CAPABILITIES)
        self.compiler = TemplateCompiler(
            deployment_capabilities=self.deployment_capabilities
        )

    def _set_local_trust_and_compile(
        self,
        version: ScenarioTemplateVersion,
        trust_level: str,
    ) -> None:
        source = copy.deepcopy(version.source_json)
        source["template"]["trust_level"] = trust_level
        result = validate_template(
            source,
            deployment_capabilities=self.deployment_capabilities,
        )
        if not result.valid or result.source is None:
            raise TemplateLifecycleError(
                "TEMPLATE_VALIDATION_FAILED",
                "Template failed validation during lifecycle compilation",
                status_code=422,
            )
        compiled = self.compiler.compile(result.source)
        version.source_json = result.source.model_dump(mode="json")
        version.schema_version = result.source.schema_version
        version.compiled_json = compiled.compiled
        version.compiler_version = compiled.compiler_version
        version.fingerprint = compiled.fingerprint
        self.db.add(
            TemplateValidationRun(
                organization_id=version.organization_id,
                template_version_id=version.id,
                validator_version=TEMPLATE_VALIDATOR_VERSION,
                status="passed",
                issues_json=_issues(result),
                capability_snapshot_json=sorted(self.deployment_capabilities),
            )
        )

    def validate(self, version: ScenarioTemplateVersion) -> TemplateValidationRun:
        result = validate_template(
            version.source_json,
            deployment_capabilities=self.deployment_capabilities,
        )
        run = TemplateValidationRun(
            organization_id=version.organization_id,
            template_version_id=version.id,
            validator_version=TEMPLATE_VALIDATOR_VERSION,
            status="passed" if result.valid else "failed",
            issues_json=_issues(result),
            capability_snapshot_json=sorted(self.deployment_capabilities),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def compile(self, version: ScenarioTemplateVersion) -> ScenarioTemplateVersion:
        if version.status in {"published", "deprecated"}:
            if not version.compiled_json or not version.fingerprint:
                raise TemplateLifecycleError(
                    "TEMPLATE_PUBLISHED_ARTIFACT_MISSING",
                    "Published template version has no compiled artifact",
                )
            return version
        run = self.validate(version)
        if run.status != "passed":
            raise TemplateLifecycleError(
                "TEMPLATE_VALIDATION_FAILED",
                "Template validation failed",
                status_code=422,
            )
        compiled = self.compiler.compile(version.source_json)
        version.compiled_json = compiled.compiled
        version.compiler_version = compiled.compiler_version
        version.fingerprint = compiled.fingerprint
        self.db.commit()
        self.db.refresh(version)
        return version

    def create_local(
        self,
        *,
        slug: str,
        category: str,
        semantic_version: str,
        source: dict[str, Any],
    ) -> tuple[ScenarioTemplate, ScenarioTemplateVersion]:
        if self.db.scalar(
            select(ScenarioTemplate).where(ScenarioTemplate.slug == slug)
        ):
            raise TemplateLifecycleError(
                "TEMPLATE_SLUG_CONFLICT",
                f"Template slug already exists: {slug}",
            )
        normalized = _bounded_source(source)
        metadata = normalized.get("template")
        if not isinstance(metadata, dict):
            raise TemplateLifecycleError(
                "TEMPLATE_SOURCE_INVALID",
                "Template source must contain template metadata",
                status_code=422,
            )
        metadata["slug"] = slug
        metadata["version"] = semantic_version
        metadata["category"] = category
        metadata["trust_level"] = "local_draft"
        result = validate_template(
            normalized,
            deployment_capabilities=self.deployment_capabilities,
        )
        if not result.valid or result.source is None:
            raise TemplateLifecycleError(
                "TEMPLATE_VALIDATION_FAILED",
                "Initial template source must pass structural and semantic validation",
                status_code=422,
            )
        template = ScenarioTemplate(
            organization_id=tenant_organization_or_legacy(self.db),
            slug=slug,
            category=category,
            owner_scope="local",
            status="active",
        )
        self.db.add(template)
        self.db.flush()
        version = ScenarioTemplateVersion(
            organization_id=template.organization_id,
            template_id=template.id,
            semantic_version=semantic_version,
            schema_version=result.source.schema_version,
            status="draft",
            source_json=result.source.model_dump(mode="json"),
            evaluation_summary_json={},
        )
        self.db.add(version)
        self.db.flush()
        self.db.add(
            TemplateValidationRun(
                organization_id=template.organization_id,
                template_version_id=version.id,
                validator_version=TEMPLATE_VALIDATOR_VERSION,
                status="passed",
                issues_json=_issues(result),
                capability_snapshot_json=sorted(self.deployment_capabilities),
            )
        )
        self.db.commit()
        self.db.refresh(template)
        self.db.refresh(version)
        return template, version

    def replace_source(
        self,
        version: ScenarioTemplateVersion,
        source: dict[str, Any],
    ) -> ScenarioTemplateVersion:
        if version.status != "draft":
            raise TemplateLifecycleError(
                "TEMPLATE_VERSION_IMMUTABLE",
                "Only draft template versions can be replaced",
            )
        normalized = _bounded_source(source)
        metadata = normalized.get("template")
        if isinstance(metadata, dict):
            metadata["slug"] = version.template.slug
            metadata["version"] = version.semantic_version
            metadata["category"] = version.template.category
            metadata["trust_level"] = "local_draft"
        result = validate_template(
            normalized,
            deployment_capabilities=self.deployment_capabilities,
        )
        if not result.valid or result.source is None:
            raise TemplateLifecycleError(
                "TEMPLATE_VALIDATION_FAILED",
                "Replacement template source failed validation",
                status_code=422,
            )
        version.source_json = result.source.model_dump(mode="json")
        version.schema_version = result.source.schema_version
        version.compiled_json = None
        version.compiler_version = None
        version.fingerprint = None
        version.evaluation_summary_json = {}
        self.db.commit()
        self.db.refresh(version)
        return version

    def clone(
        self,
        version: ScenarioTemplateVersion,
        *,
        semantic_version: str,
    ) -> ScenarioTemplateVersion:
        existing = self.db.scalar(
            select(ScenarioTemplateVersion).where(
                ScenarioTemplateVersion.template_id == version.template_id,
                ScenarioTemplateVersion.semantic_version == semantic_version,
            )
        )
        if existing:
            raise TemplateLifecycleError(
                "TEMPLATE_VERSION_CONFLICT",
                f"Template version already exists: {semantic_version}",
            )
        source = copy.deepcopy(version.source_json)
        source["template"]["version"] = semantic_version
        source["template"]["trust_level"] = "local_draft"
        result = validate_template(
            source,
            deployment_capabilities=self.deployment_capabilities,
        )
        if not result.valid or result.source is None:
            raise TemplateLifecycleError(
                "TEMPLATE_VALIDATION_FAILED",
                "Cloned template source failed validation",
                status_code=422,
            )
        cloned = ScenarioTemplateVersion(
            organization_id=version.organization_id,
            template_id=version.template_id,
            semantic_version=semantic_version,
            schema_version=result.source.schema_version,
            status="draft",
            source_json=result.source.model_dump(mode="json"),
            evaluation_summary_json={},
            created_from_version_id=version.id,
        )
        self.db.add(cloned)
        self.db.commit()
        self.db.refresh(cloned)
        return cloned

    def transition(
        self,
        version: ScenarioTemplateVersion,
        *,
        status: str,
        evaluation_summary: dict[str, Any] | None = None,
    ) -> ScenarioTemplateVersion:
        if status not in TEMPLATE_VERSION_STATES:
            raise TemplateLifecycleError(
                "TEMPLATE_STATUS_INVALID",
                f"Unsupported template status: {status}",
                status_code=422,
            )
        if status not in TEMPLATE_TRANSITIONS[version.status]:
            raise TemplateLifecycleError(
                "TEMPLATE_STATUS_TRANSITION_INVALID",
                f"Invalid template status transition: {version.status} -> {status}",
            )
        if status == "candidate":
            run = latest_validation_run(self.db, version.id)
            if run is None or run.status != "passed":
                raise TemplateLifecycleError(
                    "TEMPLATE_VALIDATION_REQUIRED",
                    "Candidate transition requires a passing validation run",
                )
            if not version.compiled_json or not version.fingerprint:
                raise TemplateLifecycleError(
                    "TEMPLATE_COMPILATION_REQUIRED",
                    "Candidate transition requires a compiled artifact",
                )
            if version.template.owner_scope == "local":
                self._set_local_trust_and_compile(version, "local_candidate")
        if status == "published":
            run = latest_validation_run(self.db, version.id)
            if run is None or run.status != "passed":
                raise TemplateLifecycleError(
                    "TEMPLATE_VALIDATION_REQUIRED",
                    "Publication requires a passing validation run",
                )
            if not version.compiled_json or not version.fingerprint:
                raise TemplateLifecycleError(
                    "TEMPLATE_COMPILATION_REQUIRED",
                    "Publication requires a compiled artifact",
                )
            summary = evaluation_summary or {}
            fixture_count = summary.get("fixture_count")
            if (
                summary.get("status") != "passed"
                or type(fixture_count) is not int
                or fixture_count < 1
            ):
                raise TemplateLifecycleError(
                    "TEMPLATE_EVALUATION_REQUIRED",
                    "Publication requires a passing behavioral evaluation summary",
                )
            if version.template.owner_scope == "local":
                self._set_local_trust_and_compile(version, "local_published")
            version.evaluation_summary_json = copy.deepcopy(summary)
            version.published_at = _now()
        elif status == "draft":
            if version.template.owner_scope == "local":
                source = copy.deepcopy(version.source_json)
                source["template"]["trust_level"] = "local_draft"
                version.source_json = source
                version.compiled_json = None
                version.compiler_version = None
                version.fingerprint = None
            version.evaluation_summary_json = {}
        version.status = status
        self.db.commit()
        self.db.refresh(version)
        return version


def seed_builtin_templates(db: Session) -> None:
    compiler = TemplateCompiler()
    for filename in BUILTIN_TEMPLATE_FILES:
        raw = load_builtin_template(filename)
        result = validate_template(raw)
        if not result.valid or result.source is None:
            raise RuntimeError(f"Built-in template failed validation: {filename}")
        source = result.source
        compiled = compiler.compile(source)
        metadata = source.template
        template = db.scalar(
            select(ScenarioTemplate).where(ScenarioTemplate.slug == metadata.slug)
        )
        if template is None:
            template = ScenarioTemplate(
                organization_id=None,
                slug=metadata.slug,
                category=metadata.category,
                owner_scope="built_in",
                status="active",
            )
            db.add(template)
            db.flush()
        elif template.owner_scope != "built_in":
            raise RuntimeError(
                f"Built-in template slug is owned by a local template: {metadata.slug}"
            )
        version = db.scalar(
            select(ScenarioTemplateVersion).where(
                ScenarioTemplateVersion.template_id == template.id,
                ScenarioTemplateVersion.semantic_version == metadata.version,
            )
        )
        source_json = source.model_dump(mode="json")
        if version is not None:
            if version.status not in {"published", "deprecated"}:
                raise RuntimeError(
                    f"Built-in template version is not immutable: "
                    f"{metadata.slug}@{metadata.version}"
                )
            if (
                canonical_json(version.source_json) != canonical_json(source_json)
                or version.fingerprint != compiled.fingerprint
                or version.compiler_version != TEMPLATE_COMPILER_VERSION
            ):
                raise RuntimeError(
                    f"Built-in template changed without a semantic version bump: "
                    f"{metadata.slug}@{metadata.version}"
                )
            current_validation = db.scalar(
                select(TemplateValidationRun).where(
                    TemplateValidationRun.template_version_id == version.id,
                    TemplateValidationRun.validator_version
                    == TEMPLATE_VALIDATOR_VERSION,
                )
            )
            if current_validation is None:
                db.add(
                    TemplateValidationRun(
                        organization_id=None,
                        template_version_id=version.id,
                        validator_version=TEMPLATE_VALIDATOR_VERSION,
                        status="passed",
                        issues_json=_issues(result),
                        capability_snapshot_json=sorted(CAPABILITIES),
                    )
                )
            continue
        version = ScenarioTemplateVersion(
            organization_id=None,
            template_id=template.id,
            semantic_version=metadata.version,
            schema_version=source.schema_version,
            status="published",
            source_json=source_json,
            compiled_json=compiled.compiled,
            compiler_version=compiled.compiler_version,
            fingerprint=compiled.fingerprint,
            evaluation_summary_json={
                "status": "passed",
                "fixture_count": 1,
                "source": "source_controlled_compatibility_suite",
            },
            published_at=_now(),
        )
        db.add(version)
        db.flush()
        db.add(
            TemplateValidationRun(
                organization_id=None,
                template_version_id=version.id,
                validator_version=TEMPLATE_VALIDATOR_VERSION,
                status="passed",
                issues_json=_issues(result),
                capability_snapshot_json=sorted(CAPABILITIES),
            )
        )
    db.commit()


def persisted_template_catalog(
    db: Session,
    *,
    category: str | None = None,
    include_drafts: bool = False,
) -> list[dict[str, Any]]:
    query = select(ScenarioTemplate).where(ScenarioTemplate.status == "active")
    if category:
        query = query.where(ScenarioTemplate.category == category)
    templates = db.scalars(query.order_by(ScenarioTemplate.slug)).all()
    catalog: list[dict[str, Any]] = []
    allowed = (
        TEMPLATE_VERSION_STATES
        if include_drafts
        else {"published"}
    )
    for template in templates:
        versions = db.scalars(
            select(ScenarioTemplateVersion)
            .where(
                ScenarioTemplateVersion.template_id == template.id,
                ScenarioTemplateVersion.status.in_(allowed),
            )
            .order_by(ScenarioTemplateVersion.created_at.desc())
        ).all()
        if not versions:
            continue
        version = versions[0]
        metadata = (version.source_json or {}).get("template") or {}
        validation = latest_validation_run(db, version.id)
        catalog.append(
            {
                "id": template.id,
                "version_id": version.id,
                "slug": template.slug,
                "version": version.semantic_version,
                "category": template.category,
                "title": metadata.get("title") or {},
                "description": metadata.get("description") or {},
                "trust_level": metadata.get("trust_level"),
                "intended_use": metadata.get("intended_use"),
                "risk_tier": metadata.get("risk_tier"),
                "lifecycle_status": version.status,
                "owner_scope": template.owner_scope,
                "fingerprint": version.fingerprint,
                "schema_version": version.schema_version,
                "validator_version": (
                    validation.validator_version
                    if validation
                    else None
                ),
                "compiler_version": version.compiler_version,
                "valid": bool(version.fingerprint),
            }
        )
    return catalog


def persisted_template_health(db: Session) -> dict[str, Any]:
    expected: dict[tuple[str, str], str] = {}
    for filename in BUILTIN_TEMPLATE_FILES:
        source = load_builtin_template(filename)
        compiled = TemplateCompiler().compile(source)
        metadata = source["template"]
        expected[(metadata["slug"], metadata["version"])] = compiled.fingerprint
    rows = db.execute(
        select(
            ScenarioTemplate.slug,
            ScenarioTemplateVersion.semantic_version,
            ScenarioTemplateVersion.fingerprint,
            ScenarioTemplateVersion.status,
        ).join(
            ScenarioTemplateVersion,
            ScenarioTemplateVersion.template_id == ScenarioTemplate.id,
        )
    ).all()
    actual = {
        (slug, semantic_version): (fingerprint, status)
        for slug, semantic_version, fingerprint, status in rows
    }
    issues: list[dict[str, str]] = []
    for identity, fingerprint in sorted(expected.items()):
        row = actual.get(identity)
        label = f"{identity[0]}@{identity[1]}"
        if row is None:
            issues.append({"code": "BUILTIN_TEMPLATE_MISSING", "template": label})
        elif row[0] != fingerprint:
            issues.append(
                {"code": "BUILTIN_TEMPLATE_FINGERPRINT_MISMATCH", "template": label}
            )
        elif row[1] not in {"published", "deprecated"}:
            issues.append(
                {"code": "BUILTIN_TEMPLATE_NOT_IMMUTABLE", "template": label}
            )
    return {
        "status": "ok" if not issues else "degraded",
        "expected_builtin_count": len(expected),
        "persisted_template_count": len({row[0] for row in rows}),
        "persisted_version_count": len(rows),
        "validator_version": TEMPLATE_VALIDATOR_VERSION,
        "compiler_version": TEMPLATE_COMPILER_VERSION,
        "issues": issues,
    }


__all__ = [
    "TemplateLifecycleError",
    "TemplateLifecycleService",
    "latest_validation_run",
    "persisted_template_catalog",
    "persisted_template_health",
    "seed_builtin_templates",
    "serialize_template",
    "serialize_template_version",
    "serialize_validation_run",
]
