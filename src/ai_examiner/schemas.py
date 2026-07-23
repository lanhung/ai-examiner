from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    domain: str = "research_defense"
    language: str = "zh-CN"


class SessionCreate(BaseModel):
    project_id: str
    blueprint_id: str
    profile: str | None = None
    mode: str = "defense"
    difficulty: str = "adaptive"
    allow_hints: bool = True
    allow_corrections: bool = True
    allow_interruptions: bool = False
    max_followups_per_question: int = Field(default=2, ge=0, le=5)
    question_limit: int = Field(default=6, ge=1, le=20)
    question_strategy: Literal["fixed", "adaptive"] = "fixed"
    learner_subject_key: str | None = Field(default=None, min_length=1, max_length=160)
    template_version_id: str | None = None
    template_overrides: dict[str, Any] = Field(default_factory=dict)


class PolicyBenchmarkCreate(BaseModel):
    question_limit: int = Field(default=2, ge=1, le=20)


class AnswerSubmit(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)


class ProviderStatus(BaseModel):
    provider: str
    model: str
    ready: bool
    note: str


class ApiMessage(BaseModel):
    message: str
    data: dict[str, Any] | None = None


class BlueprintCreate(BaseModel):
    document_id: str
    profile: str | None = None
    mode: str = "defense"
    template_version_id: str | None = None
    template_overrides: dict[str, Any] = Field(default_factory=dict)


class GoldenDatasetCreate(BaseModel):
    document_id: str
    profiles: list[str] = Field(default_factory=list, max_length=5)
    consensus_profile: str | None = None
    question_count: int = Field(default=8, ge=4, le=20)


class BenchmarkCreate(BaseModel):
    profiles: list[str] = Field(default_factory=list, max_length=6)
    case_limit: int = Field(default=4, ge=1, le=20)
    run_planner: bool = True
    run_analyzer: bool = True


class ExpertRatingCreate(BaseModel):
    case_id: str
    rater: str = Field(default="anonymous", min_length=1, max_length=120)
    relevance: int = Field(ge=1, le=5)
    difficulty: int = Field(ge=1, le=5)
    groundedness: int = Field(ge=1, le=5)
    answer_quality: int = Field(ge=1, le=5)
    notes: str = Field(default="", max_length=4000)


class VisualAnalyzeCreate(BaseModel):
    profile: str | None = None
    max_pages: int = Field(default=10, ge=1, le=100)
    asynchronous: bool = True


class JointAnalysisCreate(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=8)
    profile: str | None = None


class DatasetStatusUpdate(BaseModel):
    status: str


class PromptVersionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(default="general", max_length=80)
    content: str = Field(min_length=20, max_length=50_000)
    schema_hint: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    activate: bool = False


class ScenarioTemplateCreate(BaseModel):
    slug: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
        max_length=160,
    )
    category: Literal[
        "academic", "education", "engineering", "enterprise", "operations", "internal"
    ]
    semantic_version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$",
        max_length=80,
    )
    source: dict[str, Any]


class ScenarioTemplateCloneCreate(BaseModel):
    semantic_version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$",
        max_length=80,
    )


class ScenarioTemplateSourceUpdate(BaseModel):
    source: dict[str, Any]


class ScenarioTemplateStatusUpdate(BaseModel):
    status: Literal["draft", "candidate", "published", "deprecated"]
    evaluation_summary: dict[str, Any] = Field(default_factory=dict)


class ScenarioTemplateImport(BaseModel):
    document: str | dict[str, Any]
    target_slug: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
        max_length=160,
    )
    semantic_version: str | None = Field(
        default=None,
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$",
        max_length=80,
    )


class ProjectTemplateBindingUpdate(BaseModel):
    template_version_id: str
    default_overrides: dict[str, Any] = Field(default_factory=dict)


class AsyncGoldenDatasetCreate(GoldenDatasetCreate):
    asynchronous: bool = True


class AsyncBenchmarkCreate(BenchmarkCreate):
    asynchronous: bool = True


class VoiceSessionCreate(BaseModel):
    project_id: str
    blueprint_id: str
    provider: str = Field(default="openai", pattern="^(openai|qwen)$")
    mode: str = Field(default="defense", pattern="^(defense|teaching|interview)$")
    language: str = Field(default="zh-CN", max_length=20)
    voice: str | None = Field(default=None, max_length=40)
    vad_eagerness: str = Field(default="medium", pattern="^(low|medium|high|auto)$")
    question_limit: int = Field(default=6, ge=1, le=20)
    max_followups: int = Field(default=2, ge=0, le=5)
    allow_active_interruptions: bool = False
    question_strategy: Literal["fixed", "adaptive"] = "fixed"
    learner_subject_key: str | None = Field(default=None, max_length=160)
    analysis_profile: str | None = Field(default=None, max_length=160)
    template_version_id: str | None = None
    template_overrides: dict[str, Any] = Field(default_factory=dict)


class VoiceEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    role: str | None = Field(default=None, pattern="^(user|assistant|system)$")
    text: str = Field(default="", max_length=20_000)
    latency_ms: int | None = Field(default=None, ge=0, le=600_000)
    raw: dict[str, Any] = Field(default_factory=dict)


class VoiceSessionComplete(BaseModel):
    reason: str = Field(default="user_ended", max_length=120)


class LearnerIdentityCreate(BaseModel):
    external_subject_ref: str = Field(min_length=1, max_length=512)
    display_name: str | None = Field(default=None, max_length=200)
    memory_enabled: bool = False
    memory_scope: Literal["project_only", "linked_projects"] = "project_only"


class LearnerIdentityLinkCreate(BaseModel):
    learner_subject_id: str
    provenance: Literal["explicit", "imported", "admin_test"] = "explicit"


class MemorySettingsUpdate(BaseModel):
    memory_enabled: bool | None = None
    memory_scope: Literal["project_only", "linked_projects"] | None = None
    preference_inference_enabled: bool | None = None
    retest_planning_enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class ConceptCreate(BaseModel):
    namespace: str = Field(min_length=1, max_length=100)
    canonical_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    language: str = Field(default="zh-CN", max_length=20)


class ConceptMappingCreate(BaseModel):
    concept_id: str
    relation: Literal["exact", "narrower", "broader", "related"] = "exact"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["rule", "model", "human"] = "model"
    evidence: dict[str, Any] = Field(default_factory=dict)
    model_profile: str | None = Field(default=None, max_length=160)
    prompt_version: str | None = Field(default=None, max_length=80)


class ConceptMappingReview(BaseModel):
    status: Literal["accepted", "rejected"]


class MemoryImportCreate(BaseModel):
    dry_run: bool = False


class LongitudinalRebuildCreate(BaseModel):
    algorithm_version: Literal[
        "no-decay-v1",
        "fixed-half-life-v1",
        "evidence-half-life-v1",
    ] = "evidence-half-life-v1"
    dry_run: bool = False


class RetestPlanCreate(BaseModel):
    horizon_days: int = Field(default=14, ge=1, le=90)
    max_items: int = Field(default=8, ge=1, le=50)
    mode: Literal["shadow"] = "shadow"


class RetestItemAction(BaseModel):
    action: Literal["accept", "dismiss"]
    cooldown_days: int = Field(default=14, ge=1, le=180)


class RetestSessionCreate(BaseModel):
    blueprint_id: str
    profile: str | None = None


class PreferenceCreate(BaseModel):
    preference_key: str = Field(min_length=1, max_length=80)
    value: Any
    source: Literal["explicit", "inferred"] = "explicit"
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class PreferenceAction(BaseModel):
    action: Literal["confirm", "reject", "edit", "expire"]
    value: Any | None = None


class MemoryCorrectionCreate(BaseModel):
    observation: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=3, max_length=1000)


class MemoryExportCreate(BaseModel):
    include_source_quotes: bool = False


class MemoryDeletionCreate(BaseModel):
    scope: Literal[
        "preference",
        "concept",
        "project_link",
        "all_long_term_memory",
        "identity_and_memory",
    ]
    concept_id: str | None = None
    learner_subject_id: str | None = None
    preference_id: str | None = None
    confirmation: Literal["delete"]
