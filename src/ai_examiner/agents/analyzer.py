from __future__ import annotations

from typing import Any

from ..assessment import (
    clamp,
    expected_point_records,
    normalize_correctness,
    normalize_point_assessments,
    point_coverage,
)
from .base import BaseAgent


class AnswerAnalyzer(BaseAgent):
    name = "answer_analyzer"

    def analyze(self, *, question: dict, answer: str, history: list[dict]) -> dict:
        point_records = expected_point_records(question)
        schema = {
            "answered": True,
            "correctness": "supported|partially_supported|unsupported|insufficient",
            "claims": ["string"],
            "errors": ["string"],
            "missing_points": ["string"],
            "point_assessments": [
                {
                    "point_id": "P1",
                    "status": "covered|partial|missing|contradicted",
                    "answer_quote": "string",
                    "source_evidence_id": "string",
                    "reason": "string",
                }
            ],
            "source_grounding": 0.0,
            "reasoning_quality": 0.0,
            "boundary_awareness": 0.0,
            "confidence": 0.0,
            "followup_candidates": ["string"],
        }
        instructions = """You analyze an examinee answer. Judge only against the active question,
the identified expected points, and supplied source context. Do not reward verbosity or require exact
wording when a semantic paraphrase is correct. Assess every expected point exactly once and quote the
answer fragment that supports each covered or partial decision. Distinguish a factual contradiction from
a missing detail. Score source grounding, reasoning quality, and boundary awareness independently from
0 to 1. When question_context is followup, judge the active follow-up text; the parent question is context
only. Do not invent facts. Return calibrated confidence."""
        payload = {
            "question": {**question, "expected_point_records": point_records},
            "answer": answer,
            "recent_history": history[-4:],
        }
        data = self._json(instructions, payload, schema)
        try:
            return self._normalize(data, point_records)
        except ValueError as error:
            corrected = self._json(
                """Correct a prior Answer Analyzer result that violated the required assessment
contract. Preserve the substantive judgement, but use only the allowed enum labels and assess every
expected point exactly once. Return the complete corrected object.""",
                {**payload, "invalid_result": data, "validation_error": str(error)},
                schema,
            )
            return self._normalize(corrected, point_records)

    @staticmethod
    def _normalize(data: dict[str, Any], point_records: list[dict[str, Any]]) -> dict:
        raw_correctness = str(data.get("correctness") or "")
        correctness = normalize_correctness(raw_correctness)
        point_assessments = normalize_point_assessments(
            data.get("point_assessments"), point_records
        )
        normalized = dict(data)
        normalized.update(
            {
                "assessment_version": "answer-analyzer-v2",
                "raw_correctness": raw_correctness,
                "correctness": correctness.value,
                "point_assessments": point_assessments,
                "coverage": round(point_coverage(point_assessments), 4),
                "source_grounding": clamp(data.get("source_grounding"), 0.0),
                "reasoning_quality": clamp(data.get("reasoning_quality"), 0.0),
                "boundary_awareness": clamp(data.get("boundary_awareness"), 0.0),
                "confidence": clamp(data.get("confidence"), 0.5),
            }
        )
        normalized["evidence_present"] = normalized["source_grounding"] >= 0.5
        for key in ("claims", "errors", "missing_points", "followup_candidates"):
            normalized[key] = list(normalized.get(key) or [])
        normalized["answered"] = bool(normalized.get("answered", True))
        return normalized
