from __future__ import annotations

from enum import StrEnum
from typing import Any


class Correctness(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT = "insufficient"


class PointStatus(StrEnum):
    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"
    CONTRADICTED = "contradicted"


CORRECTNESS_VALUES = {
    Correctness.SUPPORTED: 1.0,
    Correctness.PARTIALLY_SUPPORTED: 0.65,
    Correctness.UNSUPPORTED: 0.25,
    Correctness.INSUFFICIENT: 0.10,
}

CORRECTNESS_ALIASES = {
    "correct": Correctness.SUPPORTED,
    "fully_correct": Correctness.SUPPORTED,
    "fully_supported": Correctness.SUPPORTED,
    "partial": Correctness.PARTIALLY_SUPPORTED,
    "partially_correct": Correctness.PARTIALLY_SUPPORTED,
    "incorrect": Correctness.UNSUPPORTED,
    "wrong": Correctness.UNSUPPORTED,
    "not_answered": Correctness.INSUFFICIENT,
    "unanswered": Correctness.INSUFFICIENT,
}

POINT_STATUS_ALIASES = {
    "full": PointStatus.COVERED,
    "fully_covered": PointStatus.COVERED,
    "partially_covered": PointStatus.PARTIAL,
    "absent": PointStatus.MISSING,
    "not_covered": PointStatus.MISSING,
    "incorrect": PointStatus.CONTRADICTED,
}

POINT_STATUS_VALUES = {
    PointStatus.COVERED: 1.0,
    PointStatus.PARTIAL: 0.5,
    PointStatus.MISSING: 0.0,
    PointStatus.CONTRADICTED: 0.0,
}

RUBRIC_ISSUES = {
    "none",
    "over_specific",
    "unsupported_by_context",
    "ambiguous",
}

SEMANTIC_MATCHES = {
    "equivalent",
    "partial",
    "none",
}

ASSESSMENT_WEIGHTS = {
    "correctness": 0.35,
    "coverage": 0.25,
    "source_grounding": 0.15,
    "reasoning_quality": 0.15,
    "boundary_awareness": 0.10,
}


def clamp(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(0.0, min(1.0, numeric))


def _normalized_label(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_correctness(value: Any) -> Correctness:
    label = _normalized_label(value)
    try:
        return Correctness(label)
    except ValueError:
        alias = CORRECTNESS_ALIASES.get(label)
        if alias is None:
            accepted = ", ".join(item.value for item in Correctness)
            raise ValueError(
                f"Unknown correctness label {value!r}; expected one of: {accepted}"
            ) from None
        return alias


def correctness_value(value: Any) -> float:
    return CORRECTNESS_VALUES[normalize_correctness(value)]


def normalize_point_status(value: Any) -> PointStatus:
    label = _normalized_label(value)
    try:
        return PointStatus(label)
    except ValueError:
        alias = POINT_STATUS_ALIASES.get(label)
        if alias is None:
            accepted = ", ".join(item.value for item in PointStatus)
            raise ValueError(
                f"Unknown point status {value!r}; expected one of: {accepted}"
            ) from None
        return alias


def expected_point_records(question: dict[str, Any]) -> list[dict[str, Any]]:
    points = list(question.get("expected_points") or [])
    if not points:
        active_text = str(question.get("text") or "Directly answer the active question.")
        points = [f"Directly answer the active question: {active_text}"]
    records: list[dict[str, Any]] = []
    for index, point in enumerate(points, start=1):
        if isinstance(point, dict):
            text = str(point.get("text") or point.get("description") or "").strip()
            weight = max(0.0, float(point.get("weight", 1.0)))
            point_id = str(point.get("id") or f"P{index}")
        else:
            text = str(point).strip()
            weight = 1.0
            point_id = f"P{index}"
        records.append({"id": point_id, "text": text, "weight": weight})
    return records


def normalize_point_assessments(
    raw_items: Any, expected_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("Answer Analyzer returned no point assessments")
    by_id = {
        str(item.get("point_id")): item
        for item in raw_items
        if isinstance(item, dict) and item.get("point_id")
    }
    normalized: list[dict[str, Any]] = []
    for record in expected_records:
        raw = by_id.get(str(record["id"]))
        if raw is None:
            raise ValueError(f"Answer Analyzer omitted expected point {record['id']}")
        raw_status = str(raw.get("status") or "")
        status = normalize_point_status(raw_status)
        rubric_issue = _normalized_label(raw.get("rubric_issue") or "none")
        if rubric_issue not in RUBRIC_ISSUES:
            accepted = ", ".join(sorted(RUBRIC_ISSUES))
            raise ValueError(
                f"Unknown rubric issue {raw.get('rubric_issue')!r}; "
                f"expected one of: {accepted}"
            )
        semantic_match = _normalized_label(raw.get("semantic_match") or "none")
        if semantic_match not in SEMANTIC_MATCHES:
            accepted = ", ".join(sorted(SEMANTIC_MATCHES))
            raise ValueError(
                f"Unknown semantic match {raw.get('semantic_match')!r}; "
                f"expected one of: {accepted}"
            )
        normalized.append(
            {
                "point_id": str(record["id"]),
                "point_text": str(record["text"]),
                "weight": float(record["weight"]),
                "raw_status": raw_status,
                "status": status.value,
                "answer_quote": str(raw.get("answer_quote") or "")[:500],
                "source_evidence_id": str(raw.get("source_evidence_id") or "")[:160],
                "reason": str(raw.get("reason") or "")[:1000],
                "semantic_match": semantic_match,
                "functional_criterion_satisfied": bool(
                    raw.get("functional_criterion_satisfied", False)
                ),
                "explicit_source_conflict": bool(
                    raw.get("explicit_source_conflict", False)
                ),
                "alternative_accepted": bool(raw.get("alternative_accepted", False)),
                "rubric_issue": rubric_issue,
            }
        )
    return normalized


def point_coverage(items: list[dict[str, Any]]) -> float:
    total_weight = sum(max(0.0, float(item.get("weight", 1.0))) for item in items)
    if total_weight <= 0:
        return 0.0
    covered = sum(
        max(0.0, float(item.get("weight", 1.0)))
        * POINT_STATUS_VALUES[normalize_point_status(item.get("status"))]
        for item in items
    )
    return clamp(covered / total_weight)


def assessment_components(analysis: dict[str, Any]) -> dict[str, float]:
    source_grounding = analysis.get("source_grounding")
    if source_grounding is None:
        source_grounding = 1.0 if analysis.get("evidence_present") else 0.35
    reasoning_quality = analysis.get("reasoning_quality")
    if reasoning_quality is None:
        reasoning_quality = 1.0 if analysis.get("evidence_present") else 0.35
    return {
        "correctness": correctness_value(analysis.get("correctness")),
        "coverage": clamp(analysis.get("coverage")),
        "source_grounding": clamp(source_grounding, 0.35),
        "reasoning_quality": clamp(reasoning_quality, 0.35),
        "boundary_awareness": clamp(analysis.get("boundary_awareness"), 0.5),
    }


def assessment_quality(analysis: dict[str, Any]) -> float:
    components = assessment_components(analysis)
    return sum(ASSESSMENT_WEIGHTS[key] * components[key] for key in ASSESSMENT_WEIGHTS)
