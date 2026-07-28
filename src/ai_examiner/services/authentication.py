from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from .oidc import AuthenticationContext, OIDCAuthenticator, OIDCError


@lru_cache
def get_oidc_authenticator() -> OIDCAuthenticator:
    return OIDCAuthenticator(get_settings())


def authentication_http_error(exc: OIDCError) -> HTTPException:
    status_code = {
        "authentication_required": 401,
        "token_invalid": 401,
        "authorization_denied": 403,
        "dependency_unavailable": 503,
    }.get(exc.public_code, 401)
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.public_code,
            "message": exc.public_message,
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_authentication(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> AuthenticationContext:
    settings = get_settings()
    if settings.auth_mode == "disabled":
        authentication = AuthenticationContext(
            method="disabled",
            principal_id=None,
            issuer=None,
            subject=None,
            scopes=frozenset(),
        )
        request.state.audit_authentication_method = authentication.method
        return authentication

    authorization = request.headers.get("Authorization")
    authenticator = get_oidc_authenticator()
    try:
        if authorization:
            scheme, separator, token = authorization.partition(" ")
            if separator != " " or scheme.lower() != "bearer" or not token.strip():
                raise OIDCError("authorization_header_invalid")
            authentication = authenticator.authenticate_bearer(db, token.strip())
        else:
            cookie_value = request.cookies.get(settings.oidc_session_cookie_name)
            if cookie_value:
                authentication = authenticator.authenticate_session(db, cookie_value)
            else:
                raise OIDCError(
                    "authentication_required",
                    public_code="authentication_required",
                    public_message="Authentication is required.",
                )
        request.state.audit_actor_type = (
            "principal" if authentication.principal_id else "anonymous"
        )
        request.state.audit_actor_id = authentication.principal_id
        request.state.audit_authentication_method = authentication.method
        return authentication
    except OIDCError as exc:
        request.state.audit_reason_code = exc.public_code
        raise authentication_http_error(exc) from exc


CurrentAuthentication = Annotated[
    AuthenticationContext,
    Depends(current_authentication),
]
