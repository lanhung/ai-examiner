from __future__ import annotations

import copy
from typing import Any

from ..assessment import assessment_components, clamp
from ..template_engine.registries import ASSESSMENT_DIMENSIONS, DISCLAIMER_TEXTS

TEMPLATE_ASSESSMENT_VERSION = "template-assessment-v1"
ASSISTED_BLEND = {"independent": 0.7, "assisted": 0.3}


def localized_text(value: Any, language: str, fallback: str = "") -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return fallback
    return str(
        value.get(language)
        or value.get(language.split("-", 1)[0])
        or value.get("zh-CN")
        or value.get("en")
        or next(iter(value.values()), fallback)
    )


def default_assessment_policy() -> dict[str, Any]:
    return {
        "scale": {"minimum": 0.0, "maximum": 5.0},
        "dimensions": [
            {
                "id": "correctness",
                "title": {"en": "Correctness"},
                "weight": 0.35,
                "evidence_required": True,
            },
            {
                "id": "completeness",
                "title": {"en": "Completeness"},
                "weight": 0.25,
                "evidence_required": True,
            },
            {
                "id": "evidence_reasoning",
                "title": {"en": "Evidence and reasoning"},
                "weight": 0.30,
                "evidence_required": True,
            },
            {
                "id": "boundary_awareness",
                "title": {"en": "Boundary awareness"},
                "weight": 0.10,
                "evidence_required": True,
            },
        ],
        "assisted_performance": "report_separately",
        "aggregate": "weighted_dimensions",
    }


def default_report_policy() -> dict[str, Any]:
    return {
        "sections": [
            "summary",
            "dimension_scores",
            "evidence",
            "strengths",
            "weaknesses",
            "knowledge_map",
            "improvement_path",
            "recommended_actions",
        ],
        "show_total_score": True,
        "required_disclaimer": "practice_not_formal_decision",
    }


def assessment_policy(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy((snapshot or {}).get("assessment") or default_assessment_policy())


def report_policy(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy((snapshot or {}).get("report") or default_report_policy())


def _dimension_value(dimension_id: str, components: dict[str, float]) -> float:
    definition = ASSESSMENT_DIMENSIONS[dimension_id]
    mapping = definition["components"]
    total_weight = sum(float(weight) for weight in mapping.values())
    if total_weight <= 0:
        return 0.0
    return clamp(
        sum(
            float(mapping_weight) * components.get(component_id, 0.0)
            for component_id, mapping_weight in mapping.items()
        )
        / total_weight
    )


def _dimension_evidence(
    *,
    dimension_id: str,
    answer: str,
    analysis: dict[str, Any],
    question: dict[str, Any],
) -> list[dict[str, Any]]:
    point_evidence = [
        {
            "point_id": item.get("point_id"),
            "answer_quote": str(item.get("answer_quote") or "")[:260],
            "source_evidence_id": item.get("source_evidence_id") or None,
            "status": item.get("status"),
            "reason": item.get("reason"),
        }
        for item in analysis.get("point_assessments") or []
        if item.get("answer_quote") or item.get("source_evidence_id")
    ]
    return [
        {
            "kind": "answer_and_rubric",
            "dimension_id": dimension_id,
            "answer_quote": answer[:260],
            "question_id": question.get("id"),
            "source_excerpt": question.get("source_excerpt"),
            "source_page": question.get("source_page"),
            "evidence_asset_ids": list(question.get("evidence_asset_ids") or []),
            "point_evidence": point_evidence,
        }
    ]


def evaluate_with_policy(
    *,
    question: dict[str, Any],
    answer: str,
    analysis: dict[str, Any],
    policy: dict[str, Any] | None,
    language: str = "zh-CN",
) -> dict[str, Any]:
    effective = copy.deepcopy(policy or default_assessment_policy())
    components = assessment_components(analysis)
    scale = effective.get("scale") or {"minimum": 0.0, "maximum": 5.0}
    minimum = float(scale.get("minimum", 0.0))
    maximum = float(scale.get("maximum", 5.0))
    span = maximum - minimum
    dimensions: list[dict[str, Any]] = []
    for item in effective.get("dimensions") or []:
        dimension_id = str(item["id"])
        definition = ASSESSMENT_DIMENSIONS[dimension_id]
        normalized = _dimension_value(dimension_id, components)
        anchors = copy.deepcopy(item.get("anchors") or definition["anchors"])
        dimensions.append(
            {
                "id": dimension_id,
                "title": localized_text(item.get("title"), language, dimension_id),
                "weight": float(item.get("weight", 0.0)),
                "score": round(minimum + span * normalized, 4),
                "normalized_score": round(normalized, 6),
                "evidence_required": bool(item.get("evidence_required", True)),
                "evidence": _dimension_evidence(
                    dimension_id=dimension_id,
                    answer=answer,
                    analysis=analysis,
                    question=question,
                ),
                "rubric": {
                    key: localized_text(value, language)
                    for key, value in anchors.items()
                },
            }
        )
    total_weight = sum(item["weight"] for item in dimensions)
    normalized_total = (
        sum(item["weight"] * item["normalized_score"] for item in dimensions)
        / total_weight
        if total_weight > 0
        else 0.0
    )
    computed_score = round(minimum + span * normalized_total, 4)
    return {
        "assessment_version": TEMPLATE_ASSESSMENT_VERSION,
        "aggregate": effective.get("aggregate", "weighted_dimensions"),
        "score": round(computed_score, 1),
        "computed_score": computed_score,
        "show_aggregate": effective.get("aggregate") != "no_total",
        "max_score": maximum,
        "min_score": minimum,
        "dimensions": {
            item["id"]: round(float(item["score"]), 1) for item in dimensions
        },
        "dimension_assessments": dimensions,
        "supporting_quote": answer[:260],
        "missing_points": analysis.get("missing_points", []),
        "errors": analysis.get("errors", []),
        "point_assessments": analysis.get("point_assessments", []),
        "confidence": analysis.get("confidence", 0.5),
        "question_type": question.get("type", "general"),
        "objective_ids": list(question.get("objective_ids") or []),
        "policy": {
            "assisted_performance": effective.get(
                "assisted_performance", "report_separately"
            ),
            "aggregate": effective.get("aggregate", "weighted_dimensions"),
        },
    }


def recompute_score(evaluation: dict[str, Any]) -> float:
    dimensions = evaluation.get("dimension_assessments") or []
    total_weight = sum(float(item.get("weight", 0.0)) for item in dimensions)
    if total_weight <= 0:
        return float(evaluation.get("min_score", 0.0))
    normalized = sum(
        float(item.get("weight", 0.0)) * float(item.get("normalized_score", 0.0))
        for item in dimensions
    ) / total_weight
    minimum = float(evaluation.get("min_score", 0.0))
    maximum = float(evaluation.get("max_score", 5.0))
    return round(minimum + (maximum - minimum) * normalized, 4)


def disclaimer(disclaimer_id: str, language: str) -> str:
    return localized_text(
        DISCLAIMER_TEXTS[disclaimer_id],
        language,
        disclaimer_id,
    )


__all__ = [
    "ASSISTED_BLEND",
    "TEMPLATE_ASSESSMENT_VERSION",
    "assessment_policy",
    "default_assessment_policy",
    "default_report_policy",
    "disclaimer",
    "evaluate_with_policy",
    "localized_text",
    "recompute_score",
    "report_policy",
]
