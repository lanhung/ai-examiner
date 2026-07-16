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
    question_strategy: Literal["fixed", "adaptive"] = "fixed"
    learner_subject_key: str | None = Field(default=None, max_length=160)
    analysis_profile: str | None = Field(default=None, max_length=160)


class VoiceEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    role: str | None = Field(default=None, pattern="^(user|assistant|system)$")
    text: str = Field(default="", max_length=20_000)
    latency_ms: int | None = Field(default=None, ge=0, le=600_000)
    raw: dict[str, Any] = Field(default_factory=dict)


class VoiceSessionComplete(BaseModel):
    reason: str = Field(default="user_ended", max_length=120)
