from __future__ import annotations

from .base import BaseAgent


class AnswerAnalyzer(BaseAgent):
    name = "answer_analyzer"

    def analyze(self, *, question: dict, answer: str, history: list[dict]) -> dict:
        schema = {
            "answered": True,
            "correctness": "supported|partially_supported|unsupported|insufficient",
            "coverage": 0.0,
            "claims": ["string"],
            "errors": ["string"],
            "missing_points": ["string"],
            "evidence_present": True,
            "confidence": 0.0,
            "followup_candidates": ["string"],
        }
        data = self._json(
            """You analyze an examinee answer. Judge only against the question, expected points,
and supplied source context. Do not reward verbosity. Identify unsupported claims, missing answer points,
and whether evidence or reasoning is present. Do not invent facts. Return calibrated confidence.""",
            {"question": question, "answer": answer, "recent_history": history[-4:]},
            schema,
        )
        data["coverage"] = max(0.0, min(1.0, float(data.get("coverage", 0.0))))
        data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        return data
