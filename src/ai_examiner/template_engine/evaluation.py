from __future__ import annotations

import copy
import time
from itertools import combinations
from typing import Any

from ..templates.builtin import load_builtin_template
from .catalog import BUILTIN_TEMPLATE_FILES
from .compiler import (
    TEMPLATE_COMPILER_VERSION,
    TemplateCompiler,
    TemplateOverrideError,
)
from .registries import (
    DISCLAIMER_IDS,
    PLATFORM_PROHIBITED_USES,
)
from .validator import TEMPLATE_VALIDATOR_VERSION, validate_template

TEMPLATE_EVALUATION_RUNNER_VERSION = "template-evaluation-v1"
EXPECTED_SCENARIO_COUNT = 7
MINIMUM_DISTINCT_DIMENSIONS = 3


def _version_key(value: str) -> tuple[int, int, int, str]:
    release, _, suffix = value.partition("-")
    major, minor, patch = release.split(".")
    return int(major), int(minor), int(patch), suffix


def latest_builtin_sources() -> dict[str, dict[str, Any]]:
    latest: dict[str, tuple[tuple[int, int, int, str], dict[str, Any]]] = {}
    for filename in BUILTIN_TEMPLATE_FILES:
        source = load_builtin_template(filename)
        slug = source["template"]["slug"]
        version = _version_key(source["template"]["version"])
        if slug not in latest or version > latest[slug][0]:
            latest[slug] = (version, source)
    return {slug: item[1] for slug, item in sorted(latest.items())}


def behavior_signature(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "objectives": tuple(item["id"] for item in contract["planner"]["objectives"]),
        "question_types": tuple(contract["planner"]["allowed_question_types"]),
        "question_selection": (
            contract["question_selection"]["strategy"],
            contract["question_selection"]["question_limit"],
            tuple(contract["question_selection"]["difficulty"].values()),
        ),
        "assistance": (
            contract["conversation"]["assistance"]["mode"],
            contract["conversation"]["assistance"]["hints"]["allowed"],
            contract["conversation"]["assistance"]["corrections"]["timing"],
            contract["conversation"]["assistance"]["answer_disclosure"]["allowed"],
        ),
        "conversation": (
            contract["conversation"]["max_followups_per_question"],
            tuple(contract["conversation"]["allowed_actions"]),
        ),
        "assessment": (
            tuple(
                (item["id"], item["weight"])
                for item in contract["assessment"]["dimensions"]
            ),
            contract["assessment"]["assisted_performance"],
            contract["assessment"]["aggregate"],
        ),
        "report": (
            tuple(contract["report"]["sections"]),
            contract["report"]["show_total_score"],
            contract["report"]["required_disclaimer"],
        ),
        "presentation": (
            contract["presentation"]["role_id"],
            contract["presentation"]["style_id"],
        ),
        "mode": contract["legacy"]["mode"],
    }


def _invariant_violations(
    source: dict[str, Any],
    contract: dict[str, Any],
) -> list[str]:
    violations: list[str] = []
    safety = source["safety_policy"]
    assistance = source["assistance_policy"]
    conversation = source["conversation_policy"]
    assessment = source["assessment_policy"]
    report = source["report_policy"]

    if safety["human_review_required"] is not True:
        violations.append("human_review_not_required")
    if safety["protected_trait_inference"] != "forbidden":
        violations.append("protected_trait_inference_not_forbidden")
    missing_prohibitions = PLATFORM_PROHIBITED_USES - set(safety["prohibited_uses"])
    if "protected_trait_inference" in missing_prohibitions:
        violations.append("protected_trait_prohibition_missing")
    if "personality_or_emotion_scoring" in missing_prohibitions:
        violations.append("personality_emotion_prohibition_missing")
    if report["required_disclaimer"] not in DISCLAIMER_IDS:
        violations.append("unregistered_disclaimer")
    if "END" not in conversation["allowed_actions"]:
        violations.append("terminal_action_missing")
    if conversation["interruption"]["enabled"] and not conversation["interruption"][
        "user_can_disable"
    ]:
        violations.append("active_interruption_not_user_controllable")
    if assistance["hints"]["allowed"] and assessment["assisted_performance"] not in {
        "ignore",
        "report_separately",
        "blend_with_independent",
    }:
        violations.append("assisted_performance_not_separated")
    if contract["planner"]["required_capabilities"] and not set(
        contract["planner"]["required_capabilities"]
    ):
        violations.append("required_capability_projection_invalid")
    if source["template"]["risk_tier"] == "high" and not report[
        "required_disclaimer"
    ]:
        violations.append("high_risk_disclaimer_missing")
    return violations


def _path_value(target: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = target
    for key in path:
        current = current[key]
    return current


def _override_probe_values(
    source: dict[str, Any],
    contract: dict[str, Any],
) -> list[tuple[str, Any, bool]]:
    from .registries import OVERRIDE_TARGETS

    probes: list[tuple[str, Any, bool]] = []
    for name, rule in sorted(source.get("overrides", {}).items()):
        kind = rule["kind"]
        if kind == "locked":
            value = copy.deepcopy(_path_value(contract, OVERRIDE_TARGETS[name]))
            probes.append((name, value, False))
        elif kind == "bounded":
            probes.extend(
                [
                    (name, rule["minimum"], True),
                    (name, rule["maximum"], True),
                    (name, rule["maximum"] + 1, False),
                ]
            )
        elif kind == "selectable":
            values = rule.get("values") or []
            if values:
                probes.append((name, values[0], True))
            probes.append((name, "__not_registered__", False))
        elif kind == "toggle":
            default = rule.get("default")
            if rule.get("direction") == "disable_only":
                probes.append((name, False, True))
                if default is False:
                    probes.append((name, True, False))
            else:
                probes.extend([(name, False, True), (name, True, True)])
    return probes


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return round(ordered[index], 3)


def _provider_evidence(
    reports: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    accepted: list[dict[str, Any]] = []
    providers: set[str] = set()
    for report in reports:
        if (
            report.get("probe_version") != "template-provider-probe-v1"
            or report.get("status") != "passed"
        ):
            continue
        for result in report.get("results") or []:
            profile = str(result.get("profile") or "")
            provider, separator, model = profile.partition(":")
            if (
                not separator
                or provider == "mock"
                or result.get("status") != "passed"
                or not result.get("template_results")
                or not all(
                    item.get("status") == "passed"
                    for item in result["template_results"]
                )
            ):
                continue
            providers.add(provider)
            accepted.append(
                {
                    "provider": provider,
                    "model": model,
                    "template_runs": len(result["template_results"]),
                }
            )
    held: list[str] = []
    if "qwen" not in providers:
        held.append("real_qwen_provider_sample")
    if not (providers - {"qwen"}):
        held.append("independent_real_provider_sample")
    return {
        "status": "passed" if not held else "held",
        "accepted_samples": accepted,
    }, held


def evaluate_builtin_templates(
    *,
    performance_samples: int = 25,
    provider_probe_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not 1 <= performance_samples <= 500:
        raise ValueError("performance_samples must be between 1 and 500")

    compiler = TemplateCompiler()
    sources = latest_builtin_sources()
    contracts: dict[str, dict[str, Any]] = {}
    template_results: list[dict[str, Any]] = []
    invariant_violation_count = 0

    for slug, source in sources.items():
        validation = validate_template(source)
        compiled = compiler.compile(source)
        repeat = compiler.compile(source)
        violations = _invariant_violations(source, compiled.compiled)
        invariant_violation_count += len(violations)
        contracts[slug] = compiled.compiled
        template_results.append(
            {
                "slug": slug,
                "version": source["template"]["version"],
                "valid": validation.valid,
                "validation_issue_count": len(validation.issues),
                "fingerprint": compiled.fingerprint,
                "deterministic_recompile": (
                    compiled.fingerprint == repeat.fingerprint
                    and compiled.compiled == repeat.compiled
                ),
                "objective_count": len(compiled.compiled["planner"]["objectives"]),
                "question_type_count": len(
                    compiled.compiled["planner"]["allowed_question_types"]
                ),
                "invariant_violations": violations,
            }
        )

    signatures = {
        slug: behavior_signature(contract) for slug, contract in contracts.items()
    }
    distinctness_matrix: list[dict[str, Any]] = []
    distinctness_failures = 0
    for left, right in combinations(sorted(signatures), 2):
        dimensions = [
            key
            for key in signatures[left]
            if signatures[left][key] != signatures[right][key]
        ]
        passed = len(dimensions) >= MINIMUM_DISTINCT_DIMENSIONS and bool(
            {"conversation", "assistance", "assessment"} & set(dimensions)
        )
        if not passed:
            distinctness_failures += 1
        distinctness_matrix.append(
            {
                "left": left,
                "right": right,
                "difference_count": len(dimensions),
                "different_dimensions": dimensions,
                "passed": passed,
            }
        )

    override_cases: list[dict[str, Any]] = []
    override_failures = 0
    for slug, source in sources.items():
        base = contracts[slug]
        for name, value, expected_acceptance in _override_probe_values(source, base):
            accepted = True
            error_codes: list[str] = []
            try:
                compiler.compile(source, overrides={name: value})
            except TemplateOverrideError as exc:
                accepted = False
                error_codes = [issue.code for issue in exc.issues]
            passed = accepted is expected_acceptance
            if not passed:
                override_failures += 1
            override_cases.append(
                {
                    "slug": slug,
                    "override": name,
                    "expected_acceptance": expected_acceptance,
                    "accepted": accepted,
                    "error_codes": error_codes,
                    "passed": passed,
                }
            )

    validation_ms: list[float] = []
    compilation_ms: list[float] = []
    performance_sources = list(sources.values())
    for index in range(performance_samples):
        source = performance_sources[index % len(performance_sources)]
        started = time.perf_counter()
        validate_template(source)
        validation_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        compiler.compile(source)
        compilation_ms.append((time.perf_counter() - started) * 1000)

    deterministic_passed = (
        len(sources) == EXPECTED_SCENARIO_COUNT
        and all(item["valid"] for item in template_results)
        and all(item["deterministic_recompile"] for item in template_results)
        and invariant_violation_count == 0
        and distinctness_failures == 0
        and override_failures == 0
    )
    provider_evidence, provider_held = _provider_evidence(
        provider_probe_reports or []
    )
    held_gates = [
        "scenario_relevance_frozen_corpus",
        *provider_held,
        "docker_compose_rehearsal",
        "vultr_upgrade_and_rollback_rehearsal",
    ]
    return {
        "report_version": TEMPLATE_EVALUATION_RUNNER_VERSION,
        "schema_version": "1.0",
        "validator_version": TEMPLATE_VALIDATOR_VERSION,
        "compiler_version": TEMPLATE_COMPILER_VERSION,
        "sample_counts": {
            "latest_templates": len(sources),
            "all_packaged_versions": len(BUILTIN_TEMPLATE_FILES),
            "distinctness_pairs": len(distinctness_matrix),
            "override_probes": len(override_cases),
            "performance_samples": performance_samples,
        },
        "deterministic_gates": {
            "status": "passed" if deterministic_passed else "failed",
            "template_validation": all(item["valid"] for item in template_results),
            "deterministic_recompile": all(
                item["deterministic_recompile"] for item in template_results
            ),
            "platform_invariants": invariant_violation_count == 0,
            "cross_template_distinctness": distinctness_failures == 0,
            "override_boundaries": override_failures == 0,
        },
        "templates": template_results,
        "distinctness": {
            "minimum_dimensions": MINIMUM_DISTINCT_DIMENSIONS,
            "failure_count": distinctness_failures,
            "matrix": distinctness_matrix,
        },
        "overrides": {
            "failure_count": override_failures,
            "cases": override_cases,
        },
        "performance_ms": {
            "validation_p50": _percentile(validation_ms, 0.50),
            "validation_p95": _percentile(validation_ms, 0.95),
            "compilation_p50": _percentile(compilation_ms, 0.50),
            "compilation_p95": _percentile(compilation_ms, 0.95),
            "paid_model_cost_usd": 0.0,
        },
        "release_evidence": {
            "status": "passed" if not held_gates else "held",
            "held_gates": held_gates,
            "provider_contract_samples": provider_evidence,
            "note": (
                "Deterministic gates do not substitute for provider, Docker, or "
                "Vultr release evidence."
            ),
        },
    }


__all__ = [
    "TEMPLATE_EVALUATION_RUNNER_VERSION",
    "behavior_signature",
    "evaluate_builtin_templates",
    "latest_builtin_sources",
]
