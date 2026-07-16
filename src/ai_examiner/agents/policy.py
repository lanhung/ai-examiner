from __future__ import annotations


class PolicyController:
    name = "policy_controller"

    def decide(
        self,
        *,
        analysis: dict,
        attempts: int,
        question: dict,
        config: dict,
        is_last_question: bool,
    ) -> dict:
        max_followups = int(config.get("max_followups_per_question", 2))
        coverage = float(analysis.get("coverage", 0.0))
        errors = analysis.get("errors") or []
        candidates = analysis.get("followup_candidates") or question.get("followups") or []

        if not analysis.get("answered", True) and config.get("allow_hints", True) and attempts == 0:
            return {"action": "GIVE_HINT", "reason": "answer_insufficient"}
        if (coverage < 0.72 or errors) and attempts < max_followups:
            return {
                "action": "ASK_FOLLOWUP",
                "reason": "incomplete_or_problematic",
                "followup": candidates[min(attempts, len(candidates) - 1)] if candidates else None,
            }
        if is_last_question:
            return {"action": "END", "reason": "question_limit_reached"}
        return {"action": "MOVE_ON", "reason": "sufficient_evidence"}
