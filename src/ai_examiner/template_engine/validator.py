from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, ValidationError

from .contracts import ScenarioTemplateSource
from .registries import (
    ALLOWED_ACTIONS,
    ASSESSMENT_DIMENSIONS,
    CAPABILITIES,
    DISCLAIMER_IDS,
    OVERRIDE_TARGETS,
    OVERRIDE_VALUE_TYPES,
    PLATFORM_PROHIBITED_USES,
    QUESTION_TYPES,
    REPORT_SECTIONS,
    ROLE_IDS,
    STYLE_IDS,
)

TEMPLATE_VALIDATOR_VERSION = "template-validator-v3"
WEIGHT_TOLERANCE = 0.0001


class TemplateValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"] = "error"
    path: str
    message: str


class TemplateValidationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    valid: bool
    validator_version: str = TEMPLATE_VALIDATOR_VERSION
    issues: list[TemplateValidationIssue]
    source: ScenarioTemplateSource | None = None


def template_json_schema() -> dict[str, Any]:
    schema = ScenarioTemplateSource.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def _pointer(parts: Iterable[Any]) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped) if escaped else "/"


def _issue(code: str, path: str, message: str, *, warning: bool = False):
    return TemplateValidationIssue(
        code=code,
        severity="warning" if warning else "error",
        path=path,
        message=message,
    )


def _structural_issues(raw: dict[str, Any]) -> list[TemplateValidationIssue]:
    validator = Draft202012Validator(template_json_schema())
    return [
        _issue("TEMPLATE_STRUCTURAL_INVALID", _pointer(error.absolute_path), error.message)
        for error in sorted(validator.iter_errors(raw), key=lambda item: list(item.absolute_path))
    ]


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _semantic_issues(
    source: ScenarioTemplateSource,
    *,
    deployment_capabilities: set[str],
) -> list[TemplateValidationIssue]:
    issues: list[TemplateValidationIssue] = []
    objective_ids = [objective.id for objective in source.objectives]
    dimension_ids = [dimension.id for dimension in source.assessment_policy.dimensions]

    for duplicate in sorted(_duplicates(objective_ids)):
        issues.append(
            _issue(
                "OBJECTIVE_ID_DUPLICATE",
                "/objectives",
                f"Objective id is duplicated: {duplicate}",
            )
        )
    for duplicate in sorted(_duplicates(dimension_ids)):
        issues.append(
            _issue(
                "DIMENSION_ID_DUPLICATE",
                "/assessment_policy/dimensions",
                f"Assessment dimension id is duplicated: {duplicate}",
            )
        )
    for dimension_id in dimension_ids:
        if dimension_id not in ASSESSMENT_DIMENSIONS:
            issues.append(
                _issue(
                    "ASSESSMENT_DIMENSION_UNKNOWN",
                    "/assessment_policy/dimensions",
                    f"Assessment dimension has no registered deterministic rubric: {dimension_id}",
                )
            )

    objective_weight = sum(objective.weight for objective in source.objectives)
    if abs(objective_weight - 1.0) > WEIGHT_TOLERANCE:
        issues.append(
            _issue(
                "OBJECTIVE_WEIGHTS_INVALID",
                "/objectives",
                f"Objective weights must sum to 1.0, got {objective_weight:.6f}",
            )
        )
    dimension_weight = sum(
        dimension.weight for dimension in source.assessment_policy.dimensions
    )
    if (
        source.assessment_policy.aggregate == "weighted_dimensions"
        and abs(dimension_weight - 1.0) > WEIGHT_TOLERANCE
    ):
        issues.append(
            _issue(
                "DIMENSION_WEIGHTS_INVALID",
                "/assessment_policy/dimensions",
                f"Dimension weights must sum to 1.0, got {dimension_weight:.6f}",
            )
        )

    known_objectives = set(objective_ids)
    for objective_id in source.question_policy.coverage:
        if objective_id not in known_objectives:
            issues.append(
                _issue(
                    "OBJECTIVE_REFERENCE_UNKNOWN",
                    f"/question_policy/coverage/{objective_id}",
                    f"Unknown objective reference: {objective_id}",
                )
            )

    difficulty = source.question_policy.difficulty
    if not (difficulty.minimum <= difficulty.initial <= difficulty.maximum):
        issues.append(
            _issue(
                "DIFFICULTY_RANGE_INVALID",
                "/question_policy/difficulty",
                "Difficulty must satisfy minimum <= initial <= maximum",
            )
        )

    for question_type in source.question_policy.allowed_types:
        if question_type not in QUESTION_TYPES:
            issues.append(
                _issue(
                    "QUESTION_TYPE_UNKNOWN",
                    "/question_policy/allowed_types",
                    f"Unknown question type: {question_type}",
                )
            )
    for action in source.conversation_policy.allowed_actions:
        if action not in ALLOWED_ACTIONS:
            issues.append(
                _issue(
                    "POLICY_ACTION_UNKNOWN",
                    "/conversation_policy/allowed_actions",
                    f"Unknown policy action: {action}",
                )
            )
    if "END" not in source.conversation_policy.allowed_actions:
        issues.append(
            _issue(
                "TEMPLATE_TERMINAL_ACTION_REQUIRED",
                "/conversation_policy/allowed_actions",
                "Conversation policy must allow END",
            )
        )
    for section in source.report_policy.sections:
        if section not in REPORT_SECTIONS:
            issues.append(
                _issue(
                    "REPORT_SECTION_UNKNOWN",
                    "/report_policy/sections",
                    f"Unknown report section: {section}",
                )
            )
    if source.report_policy.required_disclaimer not in DISCLAIMER_IDS:
        issues.append(
            _issue(
                "DISCLAIMER_UNKNOWN",
                "/report_policy/required_disclaimer",
                f"Unknown disclaimer: {source.report_policy.required_disclaimer}",
            )
        )

    all_capabilities = [*source.capabilities.required, *source.capabilities.optional]
    for capability in all_capabilities:
        if capability not in CAPABILITIES:
            issues.append(
                _issue(
                    "CAPABILITY_UNKNOWN",
                    "/capabilities",
                    f"Unknown capability: {capability}",
                )
            )
    missing = sorted(set(source.capabilities.required) - deployment_capabilities)
    for capability in missing:
        issues.append(
            _issue(
                "TEMPLATE_CAPABILITY_UNAVAILABLE",
                "/capabilities/required",
                f"Required capability is unavailable: {capability}",
            )
        )

    if source.presentation_policy.role_id not in ROLE_IDS:
        issues.append(
            _issue(
                "ROLE_UNKNOWN",
                "/presentation_policy/role_id",
                f"Unknown role id: {source.presentation_policy.role_id}",
            )
        )
    if source.presentation_policy.style_id not in STYLE_IDS:
        issues.append(
            _issue(
                "STYLE_UNKNOWN",
                "/presentation_policy/style_id",
                f"Unknown style id: {source.presentation_policy.style_id}",
            )
        )

    if any(not dimension.evidence_required for dimension in source.assessment_policy.dimensions):
        issues.append(
            _issue(
                "ASSESSMENT_EVIDENCE_REQUIRED",
                "/assessment_policy/dimensions",
                "Every scored dimension must require answer evidence",
            )
        )
    if (
        source.assessment_policy.assisted_performance == "blend_with_independent"
        and source.assistance_policy.mode != "none"
    ):
        issues.append(
            _issue(
                "ASSISTED_SCORE_POLICY_UNSAFE",
                "/assessment_policy/assisted_performance",
                "Assisted performance cannot be blended into independent performance",
            )
        )
    if source.template.risk_tier == "high" and not source.safety_policy.human_review_required:
        issues.append(
            _issue(
                "HUMAN_REVIEW_REQUIRED",
                "/safety_policy/human_review_required",
                "High-risk templates must require human review",
            )
        )
    declared_prohibitions = set(source.safety_policy.prohibited_uses)
    missing_prohibitions = sorted(
        {
            "protected_trait_inference",
            "personality_or_emotion_scoring",
        }
        - declared_prohibitions
    )
    for prohibited_use in missing_prohibitions:
        issues.append(
            _issue(
                "PLATFORM_PROHIBITION_MISSING",
                "/safety_policy/prohibited_uses",
                f"Platform prohibition must be declared: {prohibited_use}",
            )
        )
    unknown_prohibitions = sorted(declared_prohibitions - PLATFORM_PROHIBITED_USES)
    for prohibited_use in unknown_prohibitions:
        issues.append(
            _issue(
                "PROHIBITED_USE_UNKNOWN",
                "/safety_policy/prohibited_uses",
                f"Unknown prohibited use: {prohibited_use}",
                warning=True,
            )
        )

    for name, rule in source.overrides.items():
        if name not in OVERRIDE_TARGETS and rule.kind != "locked":
            issues.append(
                _issue(
                    "OVERRIDE_TARGET_UNKNOWN",
                    f"/overrides/{name}",
                    f"Unknown override target: {name}",
                )
            )
        if rule.kind == "bounded":
            if rule.minimum is None or rule.maximum is None or rule.minimum > rule.maximum:
                issues.append(
                    _issue(
                        "OVERRIDE_BOUNDS_INVALID",
                        f"/overrides/{name}",
                        "Bounded override requires ordered minimum and maximum",
                    )
                )
            expected_type = OVERRIDE_VALUE_TYPES.get(name)
            if (
                expected_type is not None
                and rule.default is not None
                and type(rule.default) is not expected_type
            ):
                issues.append(
                    _issue(
                        "OVERRIDE_DEFAULT_INVALID",
                        f"/overrides/{name}/default",
                        f"Override default must be {expected_type.__name__}",
                    )
                )
            if not isinstance(rule.default, (int, float)) or isinstance(rule.default, bool):
                issues.append(
                    _issue(
                        "OVERRIDE_DEFAULT_INVALID",
                        f"/overrides/{name}/default",
                        "Bounded override default must be numeric",
                    )
                )
            elif (
                rule.minimum is not None
                and rule.maximum is not None
                and not rule.minimum <= rule.default <= rule.maximum
            ):
                issues.append(
                    _issue(
                        "OVERRIDE_DEFAULT_INVALID",
                        f"/overrides/{name}/default",
                        "Bounded override default is outside its range",
                    )
                )
        elif rule.kind == "selectable":
            if not rule.values or rule.default not in rule.values:
                issues.append(
                    _issue(
                        "OVERRIDE_VALUES_INVALID",
                        f"/overrides/{name}",
                        "Selectable override requires values containing its default",
                    )
                )
            expected_type = OVERRIDE_VALUE_TYPES.get(name)
            if expected_type is not None and any(
                type(value) is not expected_type for value in (rule.values or [])
            ):
                issues.append(
                    _issue(
                        "OVERRIDE_VALUES_INVALID",
                        f"/overrides/{name}/values",
                        f"Override values must be {expected_type.__name__}",
                    )
                )
        elif rule.kind == "toggle":
            if not isinstance(rule.default, bool):
                issues.append(
                    _issue(
                        "OVERRIDE_DEFAULT_INVALID",
                        f"/overrides/{name}/default",
                        "Toggle override default must be boolean",
                    )
                )
            if rule.direction == "disable_only" and rule.default is not True:
                issues.append(
                    _issue(
                        "OVERRIDE_DIRECTION_INVALID",
                        f"/overrides/{name}",
                        "disable_only toggle must default to true",
                    )
                )

    if (
        source.assistance_policy.corrections.allowed
        and source.assistance_policy.corrections.timing == "never"
    ):
        issues.append(
            _issue(
                "CORRECTION_POLICY_CONFLICT",
                "/assistance_policy/corrections",
                "Corrections cannot be allowed with timing set to never",
            )
        )
    if (
        not source.conversation_policy.interruption.enabled
        and source.conversation_policy.interruption.level != "off"
    ):
        issues.append(
            _issue(
                "INTERRUPTION_POLICY_CONFLICT",
                "/conversation_policy/interruption",
                "Disabled interruption must use level off",
            )
        )
    return issues


def validate_template(
    raw: dict[str, Any],
    *,
    deployment_capabilities: set[str] | None = None,
) -> TemplateValidationResult:
    structural = _structural_issues(raw)
    if structural:
        return TemplateValidationResult(valid=False, issues=structural)
    try:
        source = ScenarioTemplateSource.model_validate(raw)
    except ValidationError as exc:
        issues = [
            _issue(
                "TEMPLATE_STRUCTURAL_INVALID",
                _pointer(error.get("loc") or ()),
                str(error.get("msg") or "Invalid template field"),
            )
            for error in exc.errors(include_url=False)
        ]
        return TemplateValidationResult(valid=False, issues=issues)
    semantic = _semantic_issues(
        source,
        deployment_capabilities=set(deployment_capabilities or CAPABILITIES),
    )
    return TemplateValidationResult(
        valid=not any(issue.severity == "error" for issue in semantic),
        issues=semantic,
        source=source,
    )
