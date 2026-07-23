from __future__ import annotations

from typing import Any

from ..services.template_assessment import evaluate_with_policy


class Evaluator:
    name = "evaluator"

    def evaluate(
        self,
        *,
        question: dict[str, Any],
        answer: str,
        analysis: dict[str, Any],
        assessment_policy: dict[str, Any] | None = None,
        language: str = "zh-CN",
    ) -> dict[str, Any]:
        return evaluate_with_policy(
            question=question,
            answer=answer,
            analysis=analysis,
            policy=assessment_policy,
            language=language,
        )
