from __future__ import annotations


class Evaluator:
    name = "evaluator"

    def evaluate(self, *, question: dict, answer: str, analysis: dict) -> dict:
        coverage = float(analysis.get("coverage", 0.0))
        correctness_map = {
            "supported": 1.0,
            "partially_supported": 0.65,
            "unsupported": 0.25,
            "insufficient": 0.1,
        }
        correctness = correctness_map.get(analysis.get("correctness", "insufficient"), 0.3)
        evidence = 1.0 if analysis.get("evidence_present") else 0.35
        total = round((0.45 * correctness + 0.35 * coverage + 0.20 * evidence) * 5, 1)
        return {
            "score": max(0.0, min(5.0, total)),
            "max_score": 5,
            "dimensions": {
                "correctness": round(correctness * 5, 1),
                "coverage": round(coverage * 5, 1),
                "evidence_reasoning": round(evidence * 5, 1),
            },
            "supporting_quote": answer[:260],
            "missing_points": analysis.get("missing_points", []),
            "errors": analysis.get("errors", []),
            "confidence": analysis.get("confidence", 0.5),
            "question_type": question.get("type", "general"),
        }
