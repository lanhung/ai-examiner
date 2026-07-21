from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(100), default="research_defense")
    language: Mapped[str] = mapped_column(String(20), default="zh-CN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    documents: Mapped[list[Document]] = relationship(
        back_populates="project", cascade="all, delete"
    )
    blueprints: Mapped[list[Blueprint]] = relationship(
        back_populates="project", cascade="all, delete"
    )
    sessions: Mapped[list[ExamSession]] = relationship(
        back_populates="project", cascade="all, delete"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(500))
    content_text: Mapped[str] = mapped_column(Text)
    page_map: Mapped[list] = mapped_column(JSON, default=list)
    parse_warnings: Mapped[list] = mapped_column(JSON, default=list)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="documents")


class Blueprint(Base):
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


class ExamSession(Base):
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


class Turn(Base):
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


class UsageEvent(Base):
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


class GoldenDataset(Base):
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


class BenchmarkRun(Base):
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


class ExpertRating(Base):
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


class EvidenceAsset(Base):
    __tablename__ = "evidence_assets"

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
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VisualAnalysis(Base):
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


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(80), default="general")
    content: Mapped[str] = mapped_column(Text)
    schema_hint: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    celery_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JointAnalysis(Base):
    __tablename__ = "joint_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(80), default="joint_analysis:v1")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceSession(Base):
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


class VoiceEvent(Base):
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


class KnowledgeUnit(Base):
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


class QuestionKnowledgeUnit(Base):
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


class LearnerSubject(Base):
    __tablename__ = "learner_subjects"
    __table_args__ = (UniqueConstraint("project_id", "subject_key", name="uq_subject_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    subject_key: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearnerIdentity(Base):
    __tablename__ = "learner_identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opaque_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_scope: Mapped[str] = mapped_column(String(30), default="project_only")
    preference_inference_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    retest_planning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    policy_version: Mapped[str] = mapped_column(String(50), default="memory-policy-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LearnerIdentityLink(Base):
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


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (
        UniqueConstraint("namespace", "canonical_key", name="uq_concept_namespace_key"),
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


class KnowledgeUnitConceptMap(Base):
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


class LearnerMemoryEvent(Base):
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


class LearnerConceptState(Base):
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


class RetestPlan(Base):
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


class RetestItem(Base):
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
    outcome_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("learner_memory_events.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeState(Base):
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


class KnowledgeEvidenceEvent(Base):
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


class AdaptiveDecision(Base):
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
