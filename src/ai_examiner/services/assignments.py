"""Assignment (exam window) rules shared by the teacher and learner APIs.

The learner surface is deliberately narrow: a learner only ever sees the
assignment title, the introduction, the conversation text and, when allowed,
a reduced report. Blueprint content, analysis, scoring and model details stay
on the teacher side.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from ..models import Assignment, AssignmentAttempt, ExamSession, Turn

JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 6
ATTEMPT_TOKEN_HEADER = "X-AI-Examiner-Attempt-Token"
ASSIGNMENT_MODES = ("practice", "exam")
ASSIGNMENT_STATUSES = ("published", "closed")
LOCKED_ACTIONS = frozenset({"GIVE_HINT", "CORRECT"})

MODE_DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "practice": {
        "question_limit": 5,
        "max_followups_per_question": 2,
        "question_strategy": "fixed",
        "session_mode": "defense",
        "allow_hints": True,
        "allow_corrections": True,
        "profile": None,
        "template_version_id": None,
    },
    "exam": {
        "question_limit": 5,
        "max_followups_per_question": 1,
        "question_strategy": "fixed",
        "session_mode": "defense",
        "allow_hints": False,
        "allow_corrections": False,
        "profile": None,
        "template_version_id": None,
    },
}

_JOIN_CODE_SEPARATORS = re.compile(r"[\s\-_]+")


class AssignmentError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.public_message = message


def generate_join_code() -> str:
    return "".join(
        secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH)
    )


def normalize_join_code(raw: str) -> str | None:
    """Return the canonical join code, or None when it cannot be valid."""
    code = _JOIN_CODE_SEPARATORS.sub("", raw or "").upper()
    if len(code) != JOIN_CODE_LENGTH:
        return None
    if any(character not in JOIN_CODE_ALPHABET for character in code):
        return None
    return code


def freeze_session_settings(mode: str, requested: dict[str, Any]) -> dict[str, Any]:
    """Merge teacher choices into the mode defaults and freeze the result.

    Exam mode never allows hints or corrections; asking for them is an error
    rather than a silent downgrade so the teacher sees what will happen.
    """
    if mode not in MODE_DEFAULT_SETTINGS:
        raise AssignmentError(
            "assignment_mode_invalid", "Unknown assignment mode.", status_code=422
        )
    frozen = copy.deepcopy(MODE_DEFAULT_SETTINGS[mode])
    for key, value in requested.items():
        if key not in frozen:
            raise AssignmentError(
                "assignment_setting_unknown",
                f"Unknown assignment setting: {key}",
                status_code=422,
            )
        frozen[key] = value
    if mode == "exam":
        if frozen["allow_hints"] or frozen["allow_corrections"]:
            raise AssignmentError(
                "assignment_exam_assistance_forbidden",
                "Exam assignments cannot allow hints or corrections.",
                status_code=422,
            )
    frozen["exam_lock"] = mode == "exam"
    return frozen


def lock_conversation_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Remove every assistance path from an effective conversation policy."""
    locked = copy.deepcopy(policy)
    allowed = [
        action
        for action in locked.get("allowed_actions") or []
        if action not in LOCKED_ACTIONS
    ]
    if "END" not in allowed:
        allowed.append("END")
    locked["allowed_actions"] = allowed
    locked["hints"] = {"allowed": False, "maximum_per_question": 0}
    locked["corrections"] = {"allowed": False, "timing": "never"}
    locked["answer_disclosure"] = {"allowed": False}
    locked["exam_lock"] = True
    return locked


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def window_state(assignment: Assignment, now: datetime | None = None) -> str:
    """One of: closed, scheduled, open, ended."""
    current = _aware(now) or datetime.now(UTC)
    if assignment.status != "published":
        return "closed"
    opens_at = _aware(assignment.opens_at)
    closes_at = _aware(assignment.closes_at)
    if opens_at and current < opens_at:
        return "scheduled"
    if closes_at and current >= closes_at:
        return "ended"
    return "open"


def ensure_window_open(assignment: Assignment, now: datetime | None = None) -> None:
    state = window_state(assignment, now)
    if state == "open":
        return
    messages = {
        "closed": "This exam is closed.",
        "scheduled": "This exam has not opened yet.",
        "ended": "This exam has ended.",
    }
    raise AssignmentError(f"assignment_{state}", messages[state])


def ensure_attempt_allowed(
    assignment: Assignment,
    *,
    prior_attempts: int,
    learner_key: str | None,
    now: datetime | None = None,
) -> int:
    """Validate a new attempt and return its attempt number."""
    ensure_window_open(assignment, now)
    if assignment.require_learner_key and not learner_key:
        raise AssignmentError(
            "learner_key_required",
            "A learner key is required for this exam.",
            status_code=422,
        )
    if prior_attempts >= assignment.max_attempts:
        raise AssignmentError(
            "attempt_limit_reached",
            "No attempts remain for this exam.",
        )
    return prior_attempts + 1


def normalize_learner_key(raw: str | None) -> str | None:
    value = (raw or "").strip()
    # Case-insensitive matching; upper case reads naturally for student IDs.
    return value.upper() if value else None


def hash_attempt_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_attempt_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_attempt_token(token)


def verify_attempt_token(token: str | None, token_hash: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(
        hash_attempt_token(token).encode("ascii"),
        (token_hash or "").encode("ascii"),
    )


def attempt_belongs_to(
    attempt: AssignmentAttempt,
    *,
    principal_id: str | None,
    token: str | None,
) -> bool:
    if principal_id and attempt.principal_id == principal_id:
        return True
    return verify_attempt_token(token, attempt.token_hash)


def serialize_assignment(assignment: Assignment) -> dict[str, Any]:
    return {
        "id": assignment.id,
        "organization_id": assignment.organization_id,
        "project_id": assignment.project_id,
        "blueprint_id": assignment.blueprint_id,
        "title": assignment.title,
        "mode": assignment.mode,
        "status": assignment.status,
        "window_state": window_state(assignment),
        "join_code": assignment.join_code,
        "intro_text": assignment.intro_text,
        "session_settings": copy.deepcopy(assignment.session_settings or {}),
        "opens_at": iso_timestamp(assignment.opens_at),
        "closes_at": iso_timestamp(assignment.closes_at),
        "max_attempts": assignment.max_attempts,
        "require_learner_key": assignment.require_learner_key,
        "results_released": assignment.results_released,
        "created_by_principal_id": assignment.created_by_principal_id,
        "created_at": iso_timestamp(assignment.created_at),
        "updated_at": iso_timestamp(assignment.updated_at),
    }


def public_assignment_view(assignment: Assignment) -> dict[str, Any]:
    """What anyone holding the join code may see."""
    return {
        "join_code": assignment.join_code,
        "title": assignment.title,
        "mode": assignment.mode,
        "intro_text": assignment.intro_text,
        "window_state": window_state(assignment),
        "opens_at": iso_timestamp(assignment.opens_at),
        "closes_at": iso_timestamp(assignment.closes_at),
        "max_attempts": assignment.max_attempts,
        "require_learner_key": assignment.require_learner_key,
        "question_limit": int(
            (assignment.session_settings or {}).get("question_limit") or 0
        ),
    }


def learner_turn_view(turn: Turn) -> dict[str, Any]:
    return {
        "id": turn.id,
        "role": turn.role,
        "content": turn.content,
        "created_at": iso_timestamp(turn.created_at),
    }


def learner_attempt_view(
    assignment: Assignment,
    attempt: AssignmentAttempt,
    session: ExamSession,
) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "attempt_number": attempt.attempt_number,
        "display_name": attempt.display_name,
        "status": learner_session_status(session),
        "assignment": public_assignment_view(assignment),
        "turns": [learner_turn_view(turn) for turn in session.turns],
    }


def learner_session_status(session: ExamSession) -> str:
    if session.status == "completed":
        return "submitted"
    if session.status in {"created", "ready"}:
        return "not_started"
    return "in_progress"


def results_visible(assignment: Assignment) -> bool:
    return assignment.mode == "practice" or bool(assignment.results_released)


def learner_report_view(
    assignment: Assignment,
    session: ExamSession,
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reduce a full assessment report to the learner-safe summary."""
    status = learner_session_status(session)
    base = {
        "status": status,
        "title": assignment.title,
        "mode": assignment.mode,
    }
    if status != "submitted":
        return base
    if not results_visible(assignment) or report is None:
        return {**base, "results_available": False}
    return {
        **base,
        "status": "released",
        "results_available": True,
        "summary": {
            "overall_score": report.get("overall_score"),
            "max_score": report.get("max_score"),
            "questions_answered": report.get("questions_answered"),
        },
        "strengths": [
            str(item) for item in (report.get("strengths") or []) if item
        ][:5],
        "improvements": _weakness_statements(report.get("priority_weaknesses")),
        "recommended_actions": [
            str(item)
            for item in (report.get("recommended_actions") or [])
            if item
        ][:5],
        "disclaimer": report.get("disclaimer"),
    }


def _weakness_statements(raw: Any) -> list[str]:
    statements: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = str(
                item.get("statement")
                or item.get("title")
                or item.get("name")
                or ""
            )
        else:
            text = ""
        if text:
            statements.append(text)
    return statements[:5]


def iso_timestamp(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware else None


__all__ = [
    "ASSIGNMENT_MODES",
    "ASSIGNMENT_STATUSES",
    "ATTEMPT_TOKEN_HEADER",
    "AssignmentError",
    "JOIN_CODE_ALPHABET",
    "JOIN_CODE_LENGTH",
    "MODE_DEFAULT_SETTINGS",
    "attempt_belongs_to",
    "ensure_attempt_allowed",
    "ensure_window_open",
    "freeze_session_settings",
    "generate_join_code",
    "hash_attempt_token",
    "iso_timestamp",
    "issue_attempt_token",
    "learner_attempt_view",
    "learner_report_view",
    "learner_session_status",
    "learner_turn_view",
    "lock_conversation_policy",
    "normalize_join_code",
    "normalize_learner_key",
    "public_assignment_view",
    "results_visible",
    "serialize_assignment",
    "verify_attempt_token",
    "window_state",
]
