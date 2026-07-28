from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from .authentication import CurrentAuthentication
from .authorization import (
    AuthorizationError,
    authorization_http_error,
    resolve_authorization_context,
)


@dataclass(frozen=True)
class TemplateAuthoringContext:
    actor_id: str
    scope: str
    authorization_enforced: bool
    capabilities: frozenset[str] = frozenset()

    def can(self, capability: str) -> bool:
        return capability in self.capabilities


def template_authoring_context(
    request: Request,
    authentication: CurrentAuthentication,
    db: Annotated[Session, Depends(get_db)],
) -> TemplateAuthoringContext:
    """Use capability RBAC in OIDC mode and retain explicit local compatibility."""
    settings = get_settings()
    if settings.auth_mode == "oidc":
        try:
            context = resolve_authorization_context(
                db,
                authentication=authentication,
                organization_id=request.headers.get(
                    "X-AI-Examiner-Organization"
                ),
                required_capability=None,
            )
            if not context.capabilities.intersection(
                {"template.author", "template.review", "template.publish"}
            ):
                raise AuthorizationError(
                    "authorization_denied",
                    status_code=403,
                    message="The requested operation is not permitted.",
                )
        except AuthorizationError as exc:
            raise authorization_http_error(exc) from exc
        return TemplateAuthoringContext(
            actor_id=context.principal_id,
            scope=f"organization:{context.organization_id}:template.author",
            authorization_enforced=True,
            capabilities=context.capabilities,
        )

    actor = str(request.headers.get("X-AI-Examiner-Actor") or "local-operator")
    return TemplateAuthoringContext(
        actor_id=actor[:160],
        scope="local_template_authoring",
        authorization_enforced=False,
    )


__all__ = ["TemplateAuthoringContext", "template_authoring_context"]
