from __future__ import annotations

import re


def matches_question_language(text: str, language: str) -> bool:
    """Reject English-only questions in Chinese sessions, allowing technical terms."""
    text = str(text or "").strip()
    if not text:
        return False
    if not language.lower().startswith("zh"):
        return True
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))
    # A Chinese salutation alone must not conceal an English question.
    return han >= 2 and words <= max(8, han)


def resolve_session_language(session, blueprint) -> str:
    language = (session.config or {}).get("language") or (blueprint.data or {}).get(
        "response_language"
    )
    if not language:
        language = getattr(getattr(session, "project", None), "language", None)
    return str(language or "zh-CN")
