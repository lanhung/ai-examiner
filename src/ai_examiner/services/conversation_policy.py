from __future__ import annotations

import copy
from typing import Any

DEFAULT_ALLOWED_ACTIONS = [
    "ASK_FOLLOWUP",
    "GIVE_HINT",
    "MOVE_ON",
    "END",
]
CONVERSATION_POLICY_VERSION = "conversation-policy-v1"


def effective_conversation_policy(
    snapshot: dict[str, Any] | None,
    *,
    user_allows_active_interruption: bool,
    legacy_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conversation = copy.deepcopy((snapshot or {}).get("conversation") or {})
    if not conversation:
        config = legacy_config or {}
        return {
            "policy_version": CONVERSATION_POLICY_VERSION,
            "allowed_actions": list(DEFAULT_ALLOWED_ACTIONS),
            "max_followups_per_question": int(
                config.get("max_followups_per_question", 2)
            ),
            "hints": {
                "allowed": bool(config.get("allow_hints", True)),
                "maximum_per_question": 1,
            },
            "corrections": {
                "allowed": bool(config.get("allow_corrections", True)),
                "timing": "after_independent_attempt",
            },
            "answer_disclosure": {"allowed": False},
            "active_interruption": {
                "enabled": False,
                "level": "off",
                "user_can_disable": True,
            },
        }

    assistance = conversation.get("assistance") or {}
    interruption = conversation.get("interruption") or {}
    declared_interruption = bool(interruption.get("enabled", False))
    return {
        "policy_version": CONVERSATION_POLICY_VERSION,
        "allowed_actions": list(
            conversation.get("allowed_actions") or DEFAULT_ALLOWED_ACTIONS
        ),
        "max_followups_per_question": int(
            conversation.get("max_followups_per_question", 2)
        ),
        "hints": copy.deepcopy(
            assistance.get("hints")
            or {"allowed": False, "maximum_per_question": 0}
        ),
        "corrections": copy.deepcopy(
            assistance.get("corrections")
            or {"allowed": False, "timing": "never"}
        ),
        "answer_disclosure": copy.deepcopy(
            assistance.get("answer_disclosure") or {"allowed": False}
        ),
        "active_interruption": {
            "enabled": (
                declared_interruption and user_allows_active_interruption
            ),
            "declared_enabled": declared_interruption,
            "level": interruption.get("level", "off"),
            "user_can_disable": True,
        },
    }


def voice_policy_instructions(policy: dict[str, Any]) -> str:
    allowed = ", ".join(policy["allowed_actions"])
    hints = policy["hints"]
    corrections = policy["corrections"]
    disclosure = policy["answer_disclosure"]
    interruption = policy["active_interruption"]
    return "\n".join(
        [
            "Trusted effective conversation policy:",
            f"- Allowed examiner actions: {allowed}.",
            (
                "- Hints are allowed only after an independent attempt."
                if hints.get("allowed")
                else "- Do not give hints."
            ),
            (
                f"- Corrections are allowed with timing: "
                f"{corrections.get('timing', 'after_independent_attempt')}."
                if corrections.get("allowed")
                else "- Do not correct the learner during the live answer."
            ),
            (
                "- Answer disclosure is allowed within the current task boundary."
                if disclosure.get("allowed")
                else "- Never reveal ideal answers or expected answer points."
            ),
            (
                f"- Proactive examiner interruption is enabled at "
                f"{interruption.get('level', 'off')} level."
                if interruption.get("enabled")
                else "- Do not proactively interrupt the learner."
            ),
            "- The learner may always interrupt examiner audio.",
        ]
    )


__all__ = [
    "DEFAULT_ALLOWED_ACTIONS",
    "CONVERSATION_POLICY_VERSION",
    "effective_conversation_policy",
    "voice_policy_instructions",
]
