from __future__ import annotations

from ..assessment import assessment_components, assessment_quality


class Evaluator:
    name = "evaluator"

    def evaluate(self, *, question: dict, answer: str, analysis: dict) -> dict:
        components = assessment_components(analysis)
        total = round(assessment_quality(analysis) * 5, 1)
        return {
            "assessment_version": "evaluator-v2",
            "score": max(0.0, min(5.0, total)),
            "max_score": 5,
            "dimensions": {key: round(value * 5, 1) for key, value in components.items()},
            "supporting_quote": answer[:260],
            "missing_points": analysis.get("missing_points", []),
            "errors": analysis.get("errors", []),
            "point_assessments": analysis.get("point_assessments", []),
            "confidence": analysis.get("confidence", 0.5),
            "question_type": question.get("type", "general"),
        }
