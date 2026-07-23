from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class TemplateAuthoringContext:
    actor_id: str
    scope: str
    authorization_enforced: bool


def template_authoring_context(request: Request) -> TemplateAuthoringContext:
    """Single-user authorization seam to be replaced by v0.9 identity/RBAC."""
    actor = str(request.headers.get("X-AI-Examiner-Actor") or "local-operator")
    return TemplateAuthoringContext(
        actor_id=actor[:160],
        scope="local_template_authoring",
        authorization_enforced=False,
    )


__all__ = ["TemplateAuthoringContext", "template_authoring_context"]
