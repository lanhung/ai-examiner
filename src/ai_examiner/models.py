from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .enterprise_constants import LEGACY_ORGANIZATION_ID


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TenantOwnedMixin:
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        default=LEGACY_ORGANIZATION_ID,
        server_default=LEGACY_ORGANIZATION_ID,
        nullable=False,
    )


class GlobalOrTenantOwnedMixin:
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
    )


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'disabled')",
            name="ck_organization_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    projects: Mapped[list[Project]] = relationship(back_populates="organization")
    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="organization", cascade="all, delete"
    )


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_principal_issuer_subject"),
        Index("ix_principal_status", "status"),
        CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'disabled')",
            name="ck_principal_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(500))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="principal", cascade="all, delete"
    )
    browser_sessions: Mapped[list[BrowserAuthSession]] = relationship(
        back_populates="principal", cascade="all, delete"
    )


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "principal_id",
            name="uq_organization_membership_principal",
        ),
        Index(
            "ix_organization_membership_status",
            "organization_id",
            "status",
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'examiner', 'template_author', "
            "'reviewer', 'learner', 'auditor')",
            name="ck_organization_membership_role",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_organization_membership_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    principal: Mapped[Principal] = relationship(back_populates="memberships")


class OIDCLoginTransaction(Base):
    __tablename__ = "oidc_login_transactions"
    __table_args__ = (
        Index("ix_oidc_login_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    code_verifier_ciphertext: Mapped[str] = mapped_column(Text)
    nonce_hash: Mapped[str] = mapped_column(String(64))
    redirect_uri: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BrowserAuthSession(Base):
    __tablename__ = "browser_auth_sessions"
    __table_args__ = (
        Index("ix_browser_auth_session_expires", "expires_at"),
        Index("ix_browser_auth_session_principal", "principal_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principals.id", ondelete="CASCADE")
    )
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes_json: Mapped[list] = mapped_column(JSON, default=list)
    auth_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    principal: Mapped[Principal] = relationship(back_populates="browser_sessions")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        default=LEGACY_ORGANIZATION_ID,
        server_default=LEGACY_ORGANIZATION_ID,
    )
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(100), default="research_defense")
    language: Mapped[str] = mapped_column(String(20), default="zh-CN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    documents: Mapped[list[Document]] = relationship(
        back_populates="project", cascade="all, delete"
    )
    blueprints: Mapped[list[Blueprint]] = relationship(
        back_populates="project", cascade="all, delete"
    )
    sessions: Mapped[list[ExamSession]] = relationship(
        back_populates="project", cascade="all, delete"
    )
    template_bindings: Mapped[list[ProjectTemplateBinding]] = relationship(
        back_populates="project", cascade="all, delete"
    )


class ScenarioTemplate(GlobalOrTenantOwnedMixin, Base):
    __tablename__ = "scenario_templates"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "slug",
            name="uq_scenario_template_organization_slug",
        ),
        Index(
            "uq_scenario_template_global_slug",
            "slug",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
            sqlite_where=text("organization_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40))
    owner_scope: Mapped[str] = mapped_column(String(30), default="local")
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list[ScenarioTemplateVersion]] = relationship(
        back_populates="template", cascade="all, delete"
    )


class ScenarioTemplateVersion(GlobalOrTenantOwnedMixin, Base):
    __tablename__ = "scenario_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "semantic_version",
            name="uq_scenario_template_semantic_version",
        ),
        Index("ix_template_version_status", "template_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("scenario_templates.id", ondelete="CASCADE")
    )
    semantic_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    source_json: Mapped[dict] = mapped_column(JSON)
    compiled_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    compiler_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evaluation_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_from_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenario_template_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    template: Mapped[ScenarioTemplate] = relationship(back_populates="versions")
    validation_runs: Mapped[list[TemplateValidationRun]] = relationship(
        back_populates="template_version", cascade="all, delete"
    )


class TemplateValidationRun(GlobalOrTenantOwnedMixin, Base):
    __tablename__ = "template_validation_runs"
    __table_args__ = (
        Index(
            "ix_template_validation_version_created",
            "template_version_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    template_version_id: Mapped[str] = mapped_column(
        ForeignKey("scenario_template_versions.id", ondelete="CASCADE")
    )
    validator_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    issues_json: Mapped[list] = mapped_column(JSON, default=list)
    capability_snapshot_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    template_version: Mapped[ScenarioTemplateVersion] = relationship(
        back_populates="validation_runs"
    )


class ProjectTemplateBinding(TenantOwnedMixin, Base):
    __tablename__ = "project_template_bindings"
    __table_args__ = (
        Index("ix_project_template_binding_active", "project_id", "superseded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    template_version_id: Mapped[str] = mapped_column(
        ForeignKey("scenario_template_versions.id", ondelete="RESTRICT")
    )
    default_overrides_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped[Project] = relationship(back_populates="template_bindings")


_IMMUTABLE_TEMPLATE_VERSION_FIELDS = (
    "template_id",
    "semantic_version",
    "schema_version",
    "source_json",
    "compiled_json",
    "compiler_version",
    "fingerprint",
    "evaluation_summary_json",
    "created_from_version_id",
    "published_at",
)


@event.listens_for(ScenarioTemplateVersion, "before_update")
def _guard_published_template_version(_mapper, _connection, target) -> None:
    state = sa_inspect(target)
    status_history = state.attrs.status.history
    previous_status = (
        status_history.deleted[0]
        if status_history.deleted
        else target.status
    )
    if previous_status not in {"published", "deprecated"}:
        return
    changed = [
        field
        for field in _IMMUTABLE_TEMPLATE_VERSION_FIELDS
        if state.attrs[field].history.has_changes()
    ]
    if changed:
        raise ValueError(
            "Published template version is immutable: " + ", ".join(changed)
        )
    if status_history.has_changes():
        allowed = previous_status == "published" and target.status == "deprecated"
        if not allowed:
            raise ValueError(
                f"Invalid immutable template status transition: "
                f"{previous_status} -> {target.status}"
            )


@event.listens_for(ScenarioTemplateVersion, "before_delete")
def _guard_published_template_version_delete(_mapper, _connection, target) -> None:
    if target.status in {"published", "deprecated"}:
        raise ValueError("Published template version cannot be deleted")


class StoredObject(TenantOwnedMixin, Base):
    __tablename__ = "stored_objects"
    __table_args__ = (
        UniqueConstraint(
            "backend",
            "bucket",
            "object_key",
            name="uq_stored_object_locator",
        ),
        Index(
            "ix_stored_object_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        CheckConstraint(
            "status IN ('active', 'missing', 'deleted')",
            name="ck_stored_object_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(36))
    purpose: Mapped[str] = mapped_column(String(50))
    backend: Mapped[str] = mapped_column(String(20))
    bucket: Mapped[str] = mapped_column(String(255), default="")
    object_key: Mapped[str] = mapped_column(String(900))
    content_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Document(TenantOwnedMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_storage_object", "storage_object_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("stored_objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_text: Mapped[str] = mapped_column(Text)
    page_map: Mapped[list] = mapped_column(JSON, default=list)
    parse_warnings: Mapped[list] = mapped_column(JSON, default=list)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="documents")


class Blueprint(TenantOwnedMixin, Base):
    __tablename__ = "blueprints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="blueprints")


class ExamSession(TenantOwnedMixin, Base):
    __tablename__ = "exam_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    blueprint_id: Mapped[str] = mapped_column(ForeignKey("blueprints.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default="created")
    mode: Mapped[str] = mapped_column(String(50), default="defense")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(50), default="INIT")
    current_question_index: Mapped[int] = mapped_column(Integer, default=0)
    current_question_attempts: Mapped[int] = mapped_column(Integer, default=0)
    mastery_state: Mapped[dict] = mapped_column(JSON, default=dict)
    template_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenario_template_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    template_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    template_fingerprint: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    template_compiler_version: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    template_overrides_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    learner_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_subjects.id", ondelete="SET NULL"), nullable=True
    )
    question_strategy: Mapped[str] = mapped_column(String(30), default="fixed")
    policy_version: Mapped[str] = mapped_column(String(50), default="fixed-v1")
    asked_question_ids: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="sessions")
    turns: Mapped[list[Turn]] = relationship(
        back_populates="session", cascade="all, delete", order_by="Turn.created_at"
    )


class Turn(TenantOwnedMixin, Base):
    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("exam_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(50), default="message")
    content: Mapped[str] = mapped_column(Text)
    question_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ExamSession] = relationship(back_populates="turns")


class UsageEvent(TenantOwnedMixin, Base):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    json_repair_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoldenDataset(TenantOwnedMixin, Base):
    __tablename__ = "golden_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    generator_profiles: Mapped[list] = mapped_column(JSON, default=list)
    consensus_profile: Mapped[str] = mapped_column(String(150))
    data: Mapped[dict] = mapped_column(JSON)
    quality_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BenchmarkRun(TenantOwnedMixin, Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    golden_dataset_id: Mapped[str] = mapped_column(
        ForeignKey("golden_datasets.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(30), default="completed")
    profiles: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExpertRating(TenantOwnedMixin, Base):
    __tablename__ = "expert_ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    golden_dataset_id: Mapped[str] = mapped_column(
        ForeignKey("golden_datasets.id", ondelete="CASCADE")
    )
    case_id: Mapped[str] = mapped_column(String(80))
    rater: Mapped[str] = mapped_column(String(120), default="anonymous")
    ratings: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceAsset(TenantOwnedMixin, Base):
    __tablename__ = "evidence_assets"
    __table_args__ = (
        Index("ix_evidence_assets_storage_object", "storage_object_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    bbox: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    storage_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("stored_objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VisualAnalysis(TenantOwnedMixin, Base):
    __tablename__ = "visual_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    evidence_asset_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_assets.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(80), default="visual_evidence:v1")
    status: Mapped[str] = mapped_column(String(30), default="completed")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptVersion(GlobalOrTenantOwnedMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            "version",
            name="uq_prompt_organization_name_version",
        ),
        Index(
            "uq_prompt_global_name_version",
            "name",
            "version",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
            sqlite_where=text("organization_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(80), default="general")
    content: Mapped[str] = mapped_column(Text)
    schema_hint: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(GlobalOrTenantOwnedMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_event_organization_occurred",
            "organization_id",
            "occurred_at",
            "id",
        ),
        Index("ix_audit_event_request", "request_id"),
        Index(
            "ix_audit_event_actor",
            "organization_id",
            "actor_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_event_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        CheckConstraint(
            "actor_type IN ('anonymous', 'principal', 'system', 'worker')",
            name="ck_audit_event_actor_type",
        ),
        CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')",
            name="ck_audit_event_outcome",
        ),
        CheckConstraint(
            "source_ip_class IN "
            "('loopback', 'private', 'public', 'unknown')",
            name="ck_audit_event_source_ip_class",
        ),
        CheckConstraint(
            "retention_class IN ('security', 'administrative', 'sensitive_read')",
            name="ck_audit_event_retention_class",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    actor_type: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    authentication_method: Mapped[str] = mapped_column(String(30), default="unknown")
    action: Mapped[str] = mapped_column(String(160))
    resource_type: Mapped[str] = mapped_column(String(100), default="none")
    resource_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30))
    reason_code: Mapped[str] = mapped_column(String(120), default="")
    request_id: Mapped[str] = mapped_column(String(64))
    trace_id: Mapped[str] = mapped_column(String(64))
    source_ip_class: Mapped[str] = mapped_column(String(20), default="unknown")
    source_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_family: Mapped[str] = mapped_column(String(40), default="unknown")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    event_digest: Mapped[str] = mapped_column(String(64))
    retention_class: Mapped[str] = mapped_column(
        String(30),
        default="administrative",
    )
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


@event.listens_for(AuditEvent, "before_update")
def _guard_audit_event_update(_mapper, _connection, _target) -> None:
    raise ValueError("Audit events are append-only")


@event.listens_for(AuditEvent, "before_delete")
def _guard_audit_event_delete(_mapper, _connection, _target) -> None:
    raise ValueError("Audit events are append-only")


event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER IF NOT EXISTS audit_events_no_update "
        "BEFORE UPDATE ON audit_events BEGIN "
        "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
    ).execute_if(dialect="sqlite"),
)
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER IF NOT EXISTS audit_events_no_delete "
        "BEFORE DELETE ON audit_events BEGIN "
        "SELECT RAISE(ABORT, 'audit_events are append-only'); END"
    ).execute_if(dialect="sqlite"),
)


class BackgroundJob(TenantOwnedMixin, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "kind",
            "idempotency_key",
            name="uq_background_job_idempotency",
        ),
        Index(
            "ix_background_job_lease",
            "organization_id",
            "status",
            "lease_expires_at",
        ),
        CheckConstraint(
            "status IN ("
            "'queued', 'running', 'retry_scheduled', 'cancelling', "
            "'completed', 'failed', 'cancelled', 'dead_letter'"
            ")",
            name="ck_background_job_status",
        ),
        CheckConstraint(
            "authorization_mode IN ('membership', 'legacy_local')",
            name="ck_background_job_authorization_mode",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_principal_id: Mapped[str | None] = mapped_column(
        ForeignKey("principals.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    envelope_version: Mapped[int] = mapped_column(Integer, default=1)
    envelope_json: Mapped[dict] = mapped_column(JSON, default=dict)
    envelope_digest: Mapped[str] = mapped_column(String(64), default="")
    required_capability: Mapped[str] = mapped_column(String(100), default="")
    authorization_mode: Mapped[str] = mapped_column(
        String(30),
        default="legacy_local",
    )
    status: Mapped[str] = mapped_column(String(30), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    retry_class: Mapped[str] = mapped_column(String(30), default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancel_requested_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    terminal_reason: Mapped[str] = mapped_column(String(120), default="")
    celery_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JointAnalysis(TenantOwnedMixin, Base):
    __tablename__ = "joint_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(80), default="joint_analysis:v1")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceSession(TenantOwnedMixin, Base):
    __tablename__ = "voice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    blueprint_id: Mapped[str] = mapped_column(ForeignKey("blueprints.id", ondelete="CASCADE"))
    exam_session_id: Mapped[str] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50), default="openai")
    model: Mapped[str] = mapped_column(String(100))
    voice: Mapped[str] = mapped_column(String(40), default="marin")
    status: Mapped[str] = mapped_column(String(30), default="ready")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceEvent(TenantOwnedMixin, Base):
    __tablename__ = "voice_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    voice_session_id: Mapped[str] = mapped_column(
        ForeignKey("voice_sessions.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(80))
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeUnit(TenantOwnedMixin, Base):
    __tablename__ = "knowledge_units"
    __table_args__ = (UniqueConstraint("blueprint_id", "code", name="uq_knowledge_unit_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    blueprint_id: Mapped[str] = mapped_column(ForeignKey("blueprints.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[float] = mapped_column(Float, default=0.7)
    default_difficulty: Mapped[int] = mapped_column(Integer, default=3)
    prerequisite_codes: Mapped[list] = mapped_column(JSON, default=list)
    misconception_catalog: Mapped[list] = mapped_column(JSON, default=list)
    source_evidence_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuestionKnowledgeUnit(TenantOwnedMixin, Base):
    __tablename__ = "question_knowledge_units"
    __table_args__ = (
        UniqueConstraint(
            "blueprint_id", "question_id", "knowledge_unit_id", name="uq_question_knowledge_unit"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    blueprint_id: Mapped[str] = mapped_column(ForeignKey("blueprints.id", ondelete="CASCADE"))
    question_id: Mapped[str] = mapped_column(String(80))
    knowledge_unit_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_units.id", ondelete="CASCADE")
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearnerSubject(TenantOwnedMixin, Base):
    __tablename__ = "learner_subjects"
    __table_args__ = (UniqueConstraint("project_id", "subject_key", name="uq_subject_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    subject_key: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearnerIdentity(TenantOwnedMixin, Base):
    __tablename__ = "learner_identities"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "opaque_key_hash",
            name="uq_learner_identity_organization_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opaque_key_hash: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_scope: Mapped[str] = mapped_column(String(30), default="project_only")
    preference_inference_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    retest_planning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    memory_write_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_version: Mapped[str] = mapped_column(String(50), default="memory-policy-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LearnerIdentityLink(TenantOwnedMixin, Base):
    __tablename__ = "learner_identity_links"
    __table_args__ = (
        UniqueConstraint("learner_subject_id", name="uq_identity_link_subject"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_identity_id: Mapped[str] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="CASCADE")
    )
    learner_subject_id: Mapped[str] = mapped_column(
        ForeignKey("learner_subjects.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(30), default="confirmed")
    provenance: Mapped[str] = mapped_column(String(30), default="explicit")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Concept(GlobalOrTenantOwnedMixin, Base):
    __tablename__ = "concepts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "namespace",
            "canonical_key",
            name="uq_concept_organization_namespace_key",
        ),
        Index(
            "uq_concept_global_namespace_key",
            "namespace",
            "canonical_key",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
            sqlite_where=text("organization_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    namespace: Mapped[str] = mapped_column(String(100))
    canonical_key: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(20), default="zh-CN")
    status: Mapped[str] = mapped_column(String(30), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeUnitConceptMap(TenantOwnedMixin, Base):
    __tablename__ = "knowledge_unit_concept_maps"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_unit_id", "concept_id", name="uq_knowledge_unit_concept_map"
        ),
        Index("ix_concept_map_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_unit_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_units.id", ondelete="CASCADE")
    )
    concept_id: Mapped[str] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE")
    )
    relation: Mapped[str] = mapped_column(String(30), default="exact")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    source: Mapped[str] = mapped_column(String(30), default="model")
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model_profile: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LearnerMemoryEvent(TenantOwnedMixin, Base):
    __tablename__ = "learner_memory_events"
    __table_args__ = (
        UniqueConstraint(
            "source_evidence_event_id",
            "concept_id",
            "event_type",
            name="uq_memory_source_concept_type",
        ),
        Index("ix_memory_identity_time", "learner_identity_id", "occurred_at"),
        Index("ix_memory_subject_time", "learner_subject_id", "occurred_at"),
        Index("ix_memory_concept_time", "concept_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="CASCADE"), nullable=True
    )
    learner_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_subjects.id", ondelete="CASCADE"), nullable=True
    )
    concept_id: Mapped[str | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), nullable=True
    )
    source_evidence_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_evidence_events.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    policy_version: Mapped[str] = mapped_column(String(50), default="memory-policy-v1")
    algorithm_version: Mapped[str] = mapped_column(String(50), default="memory-ledger-v1")
    supersedes_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_memory_events.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LearnerConceptState(TenantOwnedMixin, Base):
    __tablename__ = "learner_concept_states"
    __table_args__ = (
        UniqueConstraint(
            "learner_identity_id", "concept_id", name="uq_learner_concept_state"
        ),
        Index("ix_concept_state_retest", "learner_identity_id", "next_retest_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_identity_id: Mapped[str] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="CASCADE")
    )
    concept_id: Mapped[str] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE")
    )
    observed_mastery: Mapped[float] = mapped_column(Float, default=0.0)
    observed_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predicted_retention: Mapped[float] = mapped_column(Float, default=0.0)
    prediction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    stability_days: Mapped[float] = mapped_column(Float, default=30.0)
    difficulty_estimate: Mapped[float] = mapped_column(Float, default=5.5)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    independent_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    assisted_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    active_misconceptions: Mapped[list] = mapped_column(JSON, default=list)
    next_retest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    algorithm_version: Mapped[str] = mapped_column(
        String(50), default="fixed-half-life-v1"
    )
    rebuilt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetestPlan(TenantOwnedMixin, Base):
    __tablename__ = "retest_plans"
    __table_args__ = (
        Index("ix_retest_plan_identity_created", "learner_identity_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_identity_id: Mapped[str] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="CASCADE")
    )
    horizon_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="shadow")
    policy_version: Mapped[str] = mapped_column(String(50), default="retest-shadow-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetestItem(TenantOwnedMixin, Base):
    __tablename__ = "retest_items"
    __table_args__ = (
        UniqueConstraint("retest_plan_id", "concept_id", name="uq_retest_plan_concept"),
        Index("ix_retest_item_due", "retest_plan_id", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    retest_plan_id: Mapped[str] = mapped_column(
        ForeignKey("retest_plans.id", ondelete="CASCADE")
    )
    concept_id: Mapped[str] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE")
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    priority: Mapped[float] = mapped_column(Float)
    reason_code: Mapped[str] = mapped_column(String(50))
    predicted_retention: Mapped[float] = mapped_column(Float)
    uncertainty: Mapped[float] = mapped_column(Float)
    source_state_version: Mapped[str] = mapped_column(String(50))
    selected_question_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    exam_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="SET NULL"), nullable=True
    )
    outcome_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_memory_events.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    dismissed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearnerPreference(TenantOwnedMixin, Base):
    __tablename__ = "learner_preferences"
    __table_args__ = (
        UniqueConstraint(
            "learner_identity_id", "preference_key", name="uq_identity_preference_key"
        ),
        Index("ix_preference_identity_status", "learner_identity_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_identity_id: Mapped[str] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="CASCADE")
    )
    preference_key: Mapped[str] = mapped_column(String(80))
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(30), default="explicit")
    status: Mapped[str] = mapped_column(String(30), default="active")
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    confirmation_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MemoryExportArtifact(TenantOwnedMixin, Base):
    __tablename__ = "memory_export_artifacts"
    __table_args__ = (
        Index("ix_memory_export_identity_created", "learner_identity_id", "created_at"),
        Index("ix_memory_export_artifacts_storage_object", "storage_object_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_identity_id: Mapped[str] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="CASCADE")
    )
    storage_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("stored_objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict)
    record_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryDeletionAudit(TenantOwnedMixin, Base):
    __tablename__ = "memory_deletion_audits"
    __table_args__ = (
        Index("ix_memory_deletion_identity_created", "learner_identity_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_identity_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_identities.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(50))
    target_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    counts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeState(TenantOwnedMixin, Base):
    __tablename__ = "knowledge_states"
    __table_args__ = (
        UniqueConstraint("session_id", "knowledge_unit_id", name="uq_session_knowledge_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="CASCADE")
    )
    learner_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_subjects.id", ondelete="SET NULL"), nullable=True
    )
    knowledge_unit_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_units.id", ondelete="CASCADE")
    )
    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    total_evidence_weight: Mapped[float] = mapped_column(Float, default=0.0)
    misconceptions: Mapped[list] = mapped_column(JSON, default=list)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeEvidenceEvent(TenantOwnedMixin, Base):
    __tablename__ = "knowledge_evidence_events"
    __table_args__ = (
        UniqueConstraint("turn_id", "knowledge_unit_id", name="uq_turn_knowledge_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="CASCADE")
    )
    turn_id: Mapped[str] = mapped_column(ForeignKey("turns.id", ondelete="CASCADE"))
    question_id: Mapped[str] = mapped_column(String(80))
    knowledge_unit_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_units.id", ondelete="CASCADE")
    )
    learner_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_subjects.id", ondelete="SET NULL"), nullable=True
    )
    observation: Mapped[float] = mapped_column(Float)
    evidence_weight: Mapped[float] = mapped_column(Float)
    correctness: Mapped[float] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float)
    evidence_reasoning: Mapped[float] = mapped_column(Float)
    analyzer_confidence: Mapped[float] = mapped_column(Float)
    assistance_level: Mapped[str] = mapped_column(String(30), default="direct")
    detected_misconceptions: Mapped[list] = mapped_column(JSON, default=list)
    resolved_misconceptions: Mapped[list] = mapped_column(JSON, default=list)
    source_type: Mapped[str] = mapped_column(String(30), default="text")
    algorithm_version: Mapped[str] = mapped_column(String(50), default="knowledge-state-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdaptiveDecision(TenantOwnedMixin, Base):
    __tablename__ = "adaptive_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="CASCADE")
    )
    turn_id: Mapped[str | None] = mapped_column(
        ForeignKey("turns.id", ondelete="SET NULL"), nullable=True
    )
    strategy: Mapped[str] = mapped_column(String(30), default="adaptive")
    action: Mapped[str] = mapped_column(String(50))
    selected_question_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    candidate_scores: Mapped[list] = mapped_column(JSON, default=list)
    policy_config: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[str] = mapped_column(String(50), default="adaptive-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
