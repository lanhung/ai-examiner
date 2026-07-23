from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from .contracts import OverrideRule, ScenarioTemplateSource
from .registries import CAPABILITIES, OVERRIDE_TARGETS, OVERRIDE_VALUE_TYPES
from .validator import TemplateValidationIssue, validate_template

TEMPLATE_COMPILER_VERSION = "template-compiler-v1"


class TemplateValidationError(ValueError):
    def __init__(self, issues: list[TemplateValidationIssue]) -> None:
        super().__init__("Template validation failed")
        self.issues = issues


class TemplateOverrideError(ValueError):
    def __init__(self, issues: list[TemplateValidationIssue]) -> None:
        super().__init__("Template override validation failed")
        self.issues = issues


class CompiledTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compiler_version: str
    schema_version: str
    fingerprint: str
    compiled: dict[str, Any]
    override_audit: list[dict[str, Any]]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _set_path(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = target
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


def _validate_override(
    name: str,
    value: Any,
    rule: OverrideRule,
) -> TemplateValidationIssue | None:
    path = f"/overrides/{name}"
    if rule.kind == "locked":
        return TemplateValidationIssue(
            code="TEMPLATE_OVERRIDE_LOCKED",
            path=path,
            message=f"Override is locked: {name}",
        )
    expected_type = OVERRIDE_VALUE_TYPES.get(name)
    if expected_type is not None and type(value) is not expected_type:
        return TemplateValidationIssue(
            code="TEMPLATE_OVERRIDE_TYPE_INVALID",
            path=path,
            message=f"Override must be {expected_type.__name__}: {name}",
        )
    if rule.kind == "bounded":
        if rule.minimum is None or rule.maximum is None or not rule.minimum <= value <= rule.maximum:
            return TemplateValidationIssue(
                code="TEMPLATE_OVERRIDE_OUT_OF_RANGE",
                path=path,
                message=f"Override is outside the allowed range: {name}",
            )
    elif rule.kind == "selectable" and value not in (rule.values or []):
        return TemplateValidationIssue(
            code="TEMPLATE_OVERRIDE_VALUE_INVALID",
            path=path,
            message=f"Override value is not allowed: {name}",
        )
    elif rule.kind == "toggle":
        if rule.direction == "disable_only" and value is True and rule.default is False:
            return TemplateValidationIssue(
                code="TEMPLATE_OVERRIDE_DIRECTION_INVALID",
                path=path,
                message=f"Override can only disable the default: {name}",
            )
    return None


class TemplateCompiler:
    def __init__(self, *, deployment_capabilities: set[str] | None = None) -> None:
        self.deployment_capabilities = set(deployment_capabilities or CAPABILITIES)

    def compile(
        self,
        source: ScenarioTemplateSource | dict[str, Any],
        *,
        overrides: dict[str, Any] | None = None,
    ) -> CompiledTemplate:
        raw = (
            source.model_dump(mode="json")
            if isinstance(source, ScenarioTemplateSource)
            else copy.deepcopy(source)
        )
        result = validate_template(
            raw,
            deployment_capabilities=self.deployment_capabilities,
        )
        if not result.valid or result.source is None:
            raise TemplateValidationError(result.issues)
        validated = result.source
        compiled = self._base_contract(validated)
        audit: list[dict[str, Any]] = []

        for name in sorted(validated.overrides):
            rule = validated.overrides[name]
            if rule.kind != "locked" and rule.default is not None:
                _set_path(compiled, OVERRIDE_TARGETS[name], copy.deepcopy(rule.default))
                audit.append(
                    {
                        "name": name,
                        "status": "default",
                        "effective": copy.deepcopy(rule.default),
                    }
                )

        requested = overrides or {}
        issues: list[TemplateValidationIssue] = []
        for name in sorted(requested):
            rule = validated.overrides.get(name)
            if rule is None:
                issues.append(
                    TemplateValidationIssue(
                        code="TEMPLATE_OVERRIDE_UNKNOWN",
                        path=f"/overrides/{name}",
                        message=f"Template does not declare this override: {name}",
                    )
                )
                continue
            issue = _validate_override(name, requested[name], rule)
            if issue:
                issues.append(issue)
                continue
            _set_path(compiled, OVERRIDE_TARGETS[name], copy.deepcopy(requested[name]))
            audit.append(
                {
                    "name": name,
                    "status": "accepted",
                    "requested": copy.deepcopy(requested[name]),
                    "effective": copy.deepcopy(requested[name]),
                }
            )
        if issues:
            raise TemplateOverrideError(issues)

        self._refresh_legacy_projection(compiled)
        compiled["override_audit"] = audit
        payload = {
            "compiler_version": TEMPLATE_COMPILER_VERSION,
            "schema_version": validated.schema_version,
            "compiled": compiled,
        }
        fingerprint = "sha256:" + hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        return CompiledTemplate(
            compiler_version=TEMPLATE_COMPILER_VERSION,
            schema_version=validated.schema_version,
            fingerprint=fingerprint,
            compiled=compiled,
            override_audit=audit,
        )

    @staticmethod
    def _refresh_legacy_projection(compiled: dict[str, Any]) -> None:
        legacy = compiled["legacy"]
        legacy.update(
            {
                "question_limit": compiled["question_selection"]["question_limit"],
                "question_strategy": compiled["question_selection"]["strategy"],
                "allow_hints": compiled["conversation"]["assistance"]["hints"][
                    "allowed"
                ],
                "allow_corrections": compiled["conversation"]["assistance"][
                    "corrections"
                ]["allowed"],
                "allow_interruptions": compiled["conversation"]["interruption"][
                    "enabled"
                ],
                "max_followups_per_question": compiled["conversation"][
                    "max_followups_per_question"
                ],
            }
        )

    @staticmethod
    def _base_contract(source: ScenarioTemplateSource) -> dict[str, Any]:
        metadata = source.template.model_dump(mode="json")
        objectives = [item.model_dump(mode="json") for item in source.objectives]
        question_policy = source.question_policy.model_dump(mode="json")
        assistance = source.assistance_policy.model_dump(mode="json")
        conversation = source.conversation_policy.model_dump(mode="json")
        conversation["assistance"] = assistance
        assessment = source.assessment_policy.model_dump(mode="json")
        report = source.report_policy.model_dump(mode="json")
        safety = source.safety_policy.model_dump(mode="json")
        presentation = source.presentation_policy.model_dump(mode="json")
        voice = source.voice_policy.model_dump(mode="json")
        compatibility = source.compatibility.model_dump(mode="json")
        return {
            "identity": metadata,
            "planner": {
                "objectives": objectives,
                "allowed_question_types": question_policy["allowed_types"],
                "coverage": question_policy["coverage"],
                "difficulty": question_policy["difficulty"],
                "required_capabilities": source.capabilities.required,
            },
            "question_selection": {
                "strategy": question_policy["selection_strategy"],
                "question_limit": question_policy["question_limit"],
                "difficulty": question_policy["difficulty"],
                "coverage": question_policy["coverage"],
                "allowed_types": question_policy["allowed_types"],
            },
            "conversation": conversation,
            "assessment": assessment,
            "report": report,
            "voice": voice,
            "safety": safety,
            "presentation": presentation,
            "legacy": {
                "mode": compatibility["mode"],
                "difficulty": compatibility["difficulty"],
                "allow_hints": assistance["hints"]["allowed"],
                "allow_corrections": assistance["corrections"]["allowed"],
                "allow_interruptions": conversation["interruption"]["enabled"],
                "max_followups_per_question": conversation["max_followups_per_question"],
                "question_limit": question_policy["question_limit"],
                "question_strategy": question_policy["selection_strategy"],
            },
        }
