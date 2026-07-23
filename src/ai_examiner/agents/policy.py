from __future__ import annotations

from typing import Any

from ..services.conversation_policy import DEFAULT_ALLOWED_ACTIONS


class PolicyController:
    name = "policy_controller"
    version = "conversation-policy-v1"

    def decide(
        self,
        *,
        analysis: dict,
        attempts: int,
        question: dict,
        config: dict,
        is_last_question: bool,
        policy_contract: dict[str, Any] | None = None,
    ) -> dict:
        policy = policy_contract or {}
        allowed = list(policy.get("allowed_actions") or DEFAULT_ALLOWED_ACTIONS)
        max_followups = int(
            policy.get(
                "max_followups_per_question",
                config.get("max_followups_per_question", 2),
            )
        )
        hints_allowed = bool(
            (policy.get("hints") or {}).get(
                "allowed",
                config.get("allow_hints", True),
            )
        )
        coverage = float(analysis.get("coverage", 0.0))
        errors = analysis.get("errors") or []
        candidates = analysis.get("followup_candidates") or question.get("followups") or []

        if not analysis.get("answered", True) and hints_allowed and attempts == 0:
            requested = {"action": "GIVE_HINT", "reason": "answer_insufficient"}
        elif (coverage < 0.72 or errors) and attempts < max_followups:
            requested = {
                "action": "ASK_FOLLOWUP",
                "reason": "incomplete_or_problematic",
                "followup": candidates[min(attempts, len(candidates) - 1)] if candidates else None,
            }
        elif is_last_question:
            requested = {"action": "END", "reason": "question_limit_reached"}
        else:
            requested = {"action": "MOVE_ON", "reason": "sufficient_evidence"}
        return self._authorize(
            requested,
            allowed=allowed,
            is_last_question=is_last_question,
            attempts=attempts,
            max_followups=max_followups,
            followup_candidates=candidates,
            policy=policy,
        )

    @staticmethod
    def _authorize(
        requested: dict[str, Any],
        *,
        allowed: list[str],
        is_last_question: bool,
        attempts: int,
        max_followups: int,
        followup_candidates: list[str],
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        requested_action = requested["action"]
        decision = dict(requested)
        fallback_reason = None
        if requested_action not in allowed:
            fallback_reason = f"action_not_allowed:{requested_action}"
            if is_last_question and "END" in allowed:
                decision = {"action": "END", "reason": "authorized_terminal_fallback"}
            elif (
                requested_action == "GIVE_HINT"
                and "ASK_FOLLOWUP" in allowed
                and attempts < max_followups
            ):
                decision = {
                    "action": "ASK_FOLLOWUP",
                    "reason": "authorized_followup_fallback",
                    "followup": (
                        followup_candidates[
                            min(attempts, len(followup_candidates) - 1)
                        ]
                        if followup_candidates
                        else None
                    ),
                }
            elif "MOVE_ON" in allowed:
                decision = {"action": "MOVE_ON", "reason": "authorized_move_on_fallback"}
            elif "END" in allowed:
                decision = {"action": "END", "reason": "authorized_terminal_fallback"}
            else:
                raise ValueError("Conversation policy has no safe executable action")
        decision["policy_audit"] = {
            "requested_action": requested_action,
            "effective_action": decision["action"],
            "allowed_actions": allowed,
            "fallback_reason": fallback_reason,
            "hints_allowed": bool((policy.get("hints") or {}).get("allowed", True)),
            "corrections_allowed": bool(
                (policy.get("corrections") or {}).get("allowed", True)
            ),
            "answer_disclosure_allowed": bool(
                (policy.get("answer_disclosure") or {}).get("allowed", False)
            ),
            "active_interruption": dict(
                policy.get("active_interruption") or {}
            ),
        }
        return decision
