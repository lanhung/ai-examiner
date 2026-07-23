from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedText(RootModel[dict[str, str]]):
    @model_validator(mode="after")
    def validate_entries(self) -> LocalizedText:
        if not self.root:
            raise ValueError("Localized text must contain at least one language")
        for language, text in self.root.items():
            if not language or len(language) > 20:
                raise ValueError("Invalid language code")
            if not text.strip() or len(text) > 10_000:
                raise ValueError("Localized text must be non-empty and bounded")
        return self


class TemplateMetadata(StrictModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=160)
    version: str = Field(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$",
        max_length=80,
    )
    category: Literal[
        "academic", "education", "engineering", "enterprise", "operations", "internal"
    ]
    title: LocalizedText
    description: LocalizedText
    trust_level: Literal[
        "built_in_reviewed",
        "local_draft",
        "local_candidate",
        "local_published",
        "deprecated",
    ]
    intended_use: Literal["practice", "practice_and_advisory", "internal_training"]
    risk_tier: Literal["low", "moderate", "high"] = "moderate"


class CapabilityPolicy(StrictModel):
    required: list[str] = Field(default_factory=list, max_length=20)
    optional: list[str] = Field(default_factory=list, max_length=20)


class Objective(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    title: LocalizedText
    weight: float = Field(ge=0.0, le=1.0)
    required_evidence: Literal["answer", "document", "document_and_answer"] = (
        "document_and_answer"
    )


class CoverageRule(StrictModel):
    minimum_questions: int = Field(default=0, ge=0, le=20)


class DifficultyPolicy(StrictModel):
    initial: int = Field(default=3, ge=1, le=5)
    minimum: int = Field(default=1, ge=1, le=5)
    maximum: int = Field(default=5, ge=1, le=5)
    adaptive: bool = False


class QuestionPolicy(StrictModel):
    allowed_types: list[str] = Field(min_length=1, max_length=30)
    coverage: dict[str, CoverageRule] = Field(default_factory=dict)
    difficulty: DifficultyPolicy = Field(default_factory=DifficultyPolicy)
    selection_strategy: Literal["fixed", "adaptive"] = "fixed"
    question_limit: int = Field(default=6, ge=1, le=20)


class HintPolicy(StrictModel):
    allowed: bool = True
    maximum_per_question: int = Field(default=1, ge=0, le=5)


class CorrectionPolicy(StrictModel):
    allowed: bool = True
    timing: Literal[
        "never", "after_independent_attempt", "after_followups", "session_end"
    ] = "after_independent_attempt"


class AnswerDisclosurePolicy(StrictModel):
    allowed: bool = False


class AssistancePolicy(StrictModel):
    mode: Literal["none", "bounded", "teaching"] = "bounded"
    hints: HintPolicy = Field(default_factory=HintPolicy)
    corrections: CorrectionPolicy = Field(default_factory=CorrectionPolicy)
    answer_disclosure: AnswerDisclosurePolicy = Field(default_factory=AnswerDisclosurePolicy)


class InterruptionPolicy(StrictModel):
    enabled: bool = False
    level: Literal["off", "low", "normal", "strict"] = "off"
    user_can_disable: bool = True


class ConversationPolicy(StrictModel):
    max_followups_per_question: int = Field(default=2, ge=0, le=5)
    allowed_actions: list[str] = Field(min_length=1, max_length=30)
    interruption: InterruptionPolicy = Field(default_factory=InterruptionPolicy)


class AssessmentScale(StrictModel):
    minimum: float = 0.0
    maximum: float = 5.0

    @model_validator(mode="after")
    def validate_order(self) -> AssessmentScale:
        if self.minimum >= self.maximum:
            raise ValueError("Assessment scale minimum must be below maximum")
        return self


class RubricAnchors(StrictModel):
    excellent: LocalizedText
    acceptable: LocalizedText
    insufficient: LocalizedText


class AssessmentDimension(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    title: LocalizedText
    weight: float = Field(ge=0.0, le=1.0)
    evidence_required: bool = True
    anchors: RubricAnchors | None = None


class AssessmentPolicy(StrictModel):
    scale: AssessmentScale = Field(default_factory=AssessmentScale)
    dimensions: list[AssessmentDimension] = Field(min_length=1, max_length=20)
    assisted_performance: Literal[
        "ignore", "report_separately", "blend_with_independent"
    ] = "report_separately"
    aggregate: Literal["weighted_dimensions", "no_total"] = "weighted_dimensions"


class ReportPolicy(StrictModel):
    sections: list[str] = Field(min_length=1, max_length=20)
    show_total_score: bool = True
    required_disclaimer: str


class SafetyPolicy(StrictModel):
    prohibited_uses: list[str] = Field(default_factory=list, max_length=30)
    human_review_required: bool = True
    protected_trait_inference: Literal["forbidden"] = "forbidden"


class PresentationPolicy(StrictModel):
    role_id: str
    style_id: str


class VoicePolicy(StrictModel):
    provider: Literal["disabled", "openai", "qwen"] = "disabled"


class CompatibilityPolicy(StrictModel):
    mode: Literal["defense", "teaching", "interview", "retest"] | None = None
    difficulty: Literal["adaptive", "fixed"] = "adaptive"


class OverrideRule(StrictModel):
    kind: Literal["locked", "bounded", "selectable", "toggle"]
    minimum: float | None = None
    maximum: float | None = None
    values: list[Any] | None = Field(default=None, max_length=30)
    default: Any | None = None
    direction: Literal["disable_only"] | None = None


class ScenarioTemplateSource(StrictModel):
    schema_version: Literal["1.0"]
    template: TemplateMetadata
    capabilities: CapabilityPolicy
    objectives: list[Objective] = Field(min_length=1, max_length=30)
    question_policy: QuestionPolicy
    assistance_policy: AssistancePolicy
    conversation_policy: ConversationPolicy
    assessment_policy: AssessmentPolicy
    report_policy: ReportPolicy
    safety_policy: SafetyPolicy
    presentation_policy: PresentationPolicy
    voice_policy: VoicePolicy = Field(default_factory=VoicePolicy)
    compatibility: CompatibilityPolicy = Field(default_factory=CompatibilityPolicy)
    overrides: dict[str, OverrideRule] = Field(default_factory=dict)
