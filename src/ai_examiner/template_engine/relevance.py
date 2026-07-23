from __future__ import annotations

import hashlib
import json
import math
from importlib.resources import files
from typing import Any

from ..templates.builtin import load_builtin_template
from .catalog import BUILTIN_TEMPLATE_FILES

RELEVANCE_CORPUS_VERSION = "v0.8-scenario-relevance-v1"
RELEVANCE_JUDGE_REPORT_VERSION = "template-relevance-judge-v1"
RELEVANCE_EVALUATION_VERSION = "template-relevance-evaluation-v1"
CASES_PER_TEMPLATE = 30
MINIMUM_RELEASE_TEMPLATES = 3
SCORE_DIMENSIONS = (
    "relevance",
    "clarity",
    "discrimination",
    "followup_usefulness",
    "rubric_fit",
    "report_actionability",
)
ANSWER_QUALITIES = (
    "excellent",
    "partial",
    "misconception",
    "evasive",
    "unsupported_claim",
)
LANGUAGES = ("zh-CN", "en")
DIFFICULTIES = (2, 3, 4)


def _version_key(value: str) -> tuple[int, int, int, str]:
    release, _, suffix = value.partition("-")
    major, minor, patch = release.split(".")
    return int(major), int(minor), int(patch), suffix


def _latest_builtin_sources() -> dict[str, dict[str, Any]]:
    latest: dict[str, tuple[tuple[int, int, int, str], dict[str, Any]]] = {}
    for filename in BUILTIN_TEMPLATE_FILES:
        source = load_builtin_template(filename)
        slug = source["template"]["slug"]
        version = _version_key(source["template"]["version"])
        if slug not in latest or version > latest[slug][0]:
            latest[slug] = (version, source)
    return {slug: item[1] for slug, item in sorted(latest.items())}


def _load_spec() -> dict[str, Any]:
    resource = files("ai_examiner.templates.evaluation").joinpath(
        "v0_8_scenario_relevance.v1.json"
    )
    spec = json.loads(resource.read_text(encoding="utf-8"))
    if spec.get("corpus_version") != RELEVANCE_CORPUS_VERSION:
        raise ValueError("Frozen relevance corpus version mismatch")
    return spec


def _localized(value: dict[str, str], language: str) -> str:
    return value[language]


def _learner_answer(
    *,
    language: str,
    quality: str,
    focus: str,
    evidence: str,
) -> str:
    if language == "zh-CN":
        templates = {
            "excellent": f"我会围绕{focus}回答，并用材料中的证据说明：{evidence}。同时会说明结论的适用边界。",
            "partial": f"我认为重点是{focus}，但目前只能说明其中一个方面，证据还不完整。",
            "misconception": f"关于{focus}，只要结果看起来更好，就可以证明方案在所有情况下都成立。",
            "evasive": "这个问题很复杂，我们做了很多工作，团队也投入了大量时间，所以整体上应该没有问题。",
            "unsupported_claim": f"关于{focus}，行业里都认为我们的结论正确，不需要额外证据。",
        }
    else:
        templates = {
            "excellent": (
                f"I will address {focus} using the stated evidence: {evidence}. "
                "I will also state the boundary of the conclusion."
            ),
            "partial": (
                f"The main issue is {focus}, but I can currently explain only one "
                "part and the supporting evidence is incomplete."
            ),
            "misconception": (
                f"For {focus}, a better-looking result proves that the approach "
                "works in every setting."
            ),
            "evasive": (
                "This is a complex issue. The team did substantial work and spent "
                "considerable time, so the overall result should be acceptable."
            ),
            "unsupported_claim": (
                f"For {focus}, the industry already agrees with our conclusion, "
                "so no additional evidence is necessary."
            ),
        }
    return templates[quality]


def expand_relevance_corpus() -> dict[str, Any]:
    spec = _load_spec()
    cases: list[dict[str, Any]] = []
    for slug in sorted(spec["scenarios"]):
        scenario = spec["scenarios"][slug]
        topics = scenario["topics"]
        index = 0
        for language in LANGUAGES:
            for difficulty in DIFFICULTIES:
                for quality in ANSWER_QUALITIES:
                    topic = topics[index % len(topics)]
                    focus = _localized(topic["focus"], language)
                    evidence = _localized(topic["evidence"], language)
                    material_prefix = (
                        "场景材料明确说明"
                        if language == "zh-CN"
                        else "The scenario material explicitly states"
                    )
                    cases.append(
                        {
                            "case_id": (
                                f"{slug}:{language}:d{difficulty}:{quality}"
                            ),
                            "template_slug": slug,
                            "language": language,
                            "difficulty": difficulty,
                            "answer_quality": quality,
                            "objective_id": topic["objective_id"],
                            "expected_question_types": topic[
                                "expected_question_types"
                            ],
                            "required_focus": focus,
                            "material": f"{material_prefix}: {evidence}",
                            "learner_answer": _learner_answer(
                                language=language,
                                quality=quality,
                                focus=focus,
                                evidence=evidence,
                            ),
                        }
                    )
                    index += 1
    canonical = json.dumps(
        cases,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "corpus_version": RELEVANCE_CORPUS_VERSION,
        "schema_version": spec["schema_version"],
        "fingerprint": hashlib.sha256(canonical).hexdigest(),
        "cases": cases,
    }


def validate_relevance_corpus() -> dict[str, Any]:
    corpus = expand_relevance_corpus()
    sources = _latest_builtin_sources()
    issues: list[dict[str, str]] = []
    counts: dict[str, dict[str, Any]] = {}
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for case in corpus["cases"]:
        by_slug.setdefault(case["template_slug"], []).append(case)

    if set(by_slug) != set(sources):
        issues.append(
            {
                "code": "template_coverage_mismatch",
                "message": "Frozen corpus template slugs do not match latest built-ins.",
            }
        )

    for slug, source in sources.items():
        cases = by_slug.get(slug, [])
        language_counts = {
            language: sum(item["language"] == language for item in cases)
            for language in LANGUAGES
        }
        difficulty_counts = {
            str(difficulty): sum(
                item["difficulty"] == difficulty for item in cases
            )
            for difficulty in DIFFICULTIES
        }
        quality_counts = {
            quality: sum(item["answer_quality"] == quality for item in cases)
            for quality in ANSWER_QUALITIES
        }
        counts[slug] = {
            "total": len(cases),
            "languages": language_counts,
            "difficulties": difficulty_counts,
            "answer_qualities": quality_counts,
        }
        if len(cases) != CASES_PER_TEMPLATE:
            issues.append(
                {
                    "code": "case_count_invalid",
                    "message": f"{slug} must contain {CASES_PER_TEMPLATE} cases.",
                }
            )
        objectives = {item["id"] for item in source["objectives"]}
        allowed_types = set(source["question_policy"]["allowed_types"])
        for case in cases:
            if case["objective_id"] not in objectives:
                issues.append(
                    {
                        "code": "objective_not_registered",
                        "message": f"{case['case_id']} has an unknown objective.",
                    }
                )
            if not set(case["expected_question_types"]) <= allowed_types:
                issues.append(
                    {
                        "code": "question_type_not_allowed",
                        "message": (
                            f"{case['case_id']} expects a type outside the template."
                        ),
                    }
                )
        if set(language_counts.values()) != {15}:
            issues.append(
                {
                    "code": "language_balance_invalid",
                    "message": f"{slug} is not balanced across languages.",
                }
            )
        if set(difficulty_counts.values()) != {10}:
            issues.append(
                {
                    "code": "difficulty_balance_invalid",
                    "message": f"{slug} is not balanced across difficulty.",
                }
            )
        if set(quality_counts.values()) != {6}:
            issues.append(
                {
                    "code": "answer_quality_balance_invalid",
                    "message": f"{slug} is not balanced across answer quality.",
                }
            )

    return {
        "status": "passed" if not issues else "failed",
        "corpus_version": corpus["corpus_version"],
        "schema_version": corpus["schema_version"],
        "fingerprint": corpus["fingerprint"],
        "case_count": len(corpus["cases"]),
        "template_count": len(by_slug),
        "counts": counts,
        "issues": issues,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mean_ci95(values: list[float]) -> list[float]:
    if not values:
        return [0.0, 0.0]
    mean = _mean(values)
    if len(values) == 1:
        return [round(mean, 3), round(mean, 3)]
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    margin = 1.96 * math.sqrt(variance / len(values))
    return [round(mean - margin, 3), round(mean + margin, 3)]


def _valid_score_set(value: Any) -> bool:
    return isinstance(value, dict) and all(
        not isinstance(value.get(dimension), bool)
        and isinstance(value.get(dimension), (int, float))
        and 1 <= float(value[dimension]) <= 5
        for dimension in SCORE_DIMENSIONS
    )


def evaluate_relevance_reports(
    reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    corpus = expand_relevance_corpus()
    corpus_validation = validate_relevance_corpus()
    case_ids = {item["case_id"] for item in corpus["cases"]}
    cases_by_template: dict[str, set[str]] = {}
    for case in corpus["cases"]:
        cases_by_template.setdefault(case["template_slug"], set()).add(
            case["case_id"]
        )

    accepted_reports: list[dict[str, Any]] = []
    rejected_reports: list[dict[str, str]] = []
    observations: dict[str, list[dict[str, Any]]] = {}

    for index, report in enumerate(reports or []):
        reason = ""
        judge_profile = str(report.get("judge_profile") or "")
        generator_profile = str(report.get("generator_profile") or "")
        judge_provider, judge_separator, judge_model = judge_profile.partition(":")
        generator_provider, generator_separator, generator_model = (
            generator_profile.partition(":")
        )
        evaluations = report.get("evaluations") or []
        if report.get("report_version") != RELEVANCE_JUDGE_REPORT_VERSION:
            reason = "unsupported_report_version"
        elif report.get("corpus_fingerprint") != corpus["fingerprint"]:
            reason = "corpus_fingerprint_mismatch"
        elif not report.get("blind_judging"):
            reason = "blind_judging_not_attested"
        elif report.get("generation_path") != "session_planner":
            reason = "runtime_session_planner_path_required"
        elif (
            not judge_provider
            or not generator_provider
            or not judge_separator
            or not generator_separator
            or not judge_model
            or not generator_model
            or judge_provider == "mock"
            or generator_provider == "mock"
            or judge_provider == generator_provider
        ):
            reason = "independent_provider_required"
        elif not evaluations:
            reason = "evaluations_missing"
        elif any(
            item.get("case_id") not in case_ids
            or not _valid_score_set(item.get("baseline"))
            or not _valid_score_set(item.get("scenario"))
            or not isinstance(item.get("grounded"), bool)
            or not isinstance(item.get("single_main_question"), bool)
            or not isinstance(item.get("unsafe_or_prohibited"), bool)
            for item in evaluations
        ):
            reason = "evaluation_contract_invalid"

        if reason:
            rejected_reports.append(
                {"report_index": str(index), "reason": reason}
            )
            continue

        accepted_reports.append(
            {
                "judge_profile": judge_profile,
                "generator_profile": generator_profile,
                "evaluation_count": len(evaluations),
            }
        )
        for item in evaluations:
            case_id = item["case_id"]
            slug = case_id.split(":", 1)[0]
            observations.setdefault(slug, []).append(
                {
                    **item,
                    "_judge_provider": judge_provider,
                    "_generator_provider": generator_provider,
                }
            )

    template_results: list[dict[str, Any]] = []
    passed_templates = 0
    for slug in sorted(cases_by_template):
        items = observations.get(slug, [])
        covered_cases = {item["case_id"] for item in items}
        judge_providers = sorted(
            {item["_judge_provider"] for item in items}
        )
        provider_pairs = {
            (item["_generator_provider"], item["_judge_provider"])
            for item in items
        }
        reciprocal_cross_judging = any(
            (judge, generator) in provider_pairs
            for generator, judge in provider_pairs
        )
        relevance_deltas = [
            float(item["scenario"]["relevance"])
            - float(item["baseline"]["relevance"])
            for item in items
        ]
        scenario_quality = [
            _mean(
                [
                    float(item["scenario"]["relevance"]),
                    float(item["scenario"]["clarity"]),
                    float(item["scenario"]["discrimination"]),
                    float(item["scenario"]["followup_usefulness"]),
                ]
            )
            for item in items
        ]
        relevance_improvement = _mean(relevance_deltas)
        high_quality_rate = (
            sum(value >= 4.0 for value in scenario_quality) / len(items)
            if items
            else 0.0
        )
        grounded_rate = (
            sum(item["grounded"] for item in items) / len(items)
            if items
            else 0.0
        )
        single_question_rate = (
            sum(item["single_main_question"] for item in items) / len(items)
            if items
            else 0.0
        )
        unsafe_rate = (
            sum(item["unsafe_or_prohibited"] for item in items) / len(items)
            if items
            else 0.0
        )
        passed = (
            covered_cases == cases_by_template[slug]
            and relevance_improvement >= 0.5
            and high_quality_rate >= 0.80
            and grounded_rate >= 0.95
            and single_question_rate >= 0.98
            and unsafe_rate == 0.0
            and len(judge_providers) >= 2
            and reciprocal_cross_judging
        )
        passed_templates += int(passed)
        template_results.append(
            {
                "template_slug": slug,
                "status": "passed" if passed else "held",
                "unique_cases": len(covered_cases),
                "judge_observations": len(items),
                "judge_providers": judge_providers,
                "reciprocal_cross_judging": reciprocal_cross_judging,
                "mean_relevance_improvement": round(relevance_improvement, 3),
                "relevance_improvement_ci95": _mean_ci95(relevance_deltas),
                "high_quality_question_rate": round(high_quality_rate, 3),
                "grounded_question_rate": round(grounded_rate, 3),
                "single_main_question_rate": round(single_question_rate, 3),
                "unsafe_or_prohibited_rate": round(unsafe_rate, 3),
            }
        )

    passed = (
        corpus_validation["status"] == "passed"
        and passed_templates >= MINIMUM_RELEASE_TEMPLATES
        and bool(accepted_reports)
    )
    return {
        "evaluation_version": RELEVANCE_EVALUATION_VERSION,
        "status": "passed" if passed else "held",
        "corpus": corpus_validation,
        "accepted_reports": accepted_reports,
        "rejected_reports": rejected_reports,
        "templates_required_for_release": MINIMUM_RELEASE_TEMPLATES,
        "templates_passed": passed_templates,
        "template_results": template_results,
        "thresholds": {
            "cases_per_template": CASES_PER_TEMPLATE,
            "mean_relevance_improvement": 0.5,
            "high_quality_question_rate": 0.80,
            "grounded_question_rate": 0.95,
            "single_main_question_rate": 0.98,
            "unsafe_or_prohibited_rate": 0.0,
            "minimum_judge_providers": 2,
            "reciprocal_cross_judging": True,
        },
    }


__all__ = [
    "ANSWER_QUALITIES",
    "CASES_PER_TEMPLATE",
    "DIFFICULTIES",
    "LANGUAGES",
    "MINIMUM_RELEASE_TEMPLATES",
    "RELEVANCE_CORPUS_VERSION",
    "RELEVANCE_EVALUATION_VERSION",
    "RELEVANCE_JUDGE_REPORT_VERSION",
    "SCORE_DIMENSIONS",
    "evaluate_relevance_reports",
    "expand_relevance_corpus",
    "validate_relevance_corpus",
]
