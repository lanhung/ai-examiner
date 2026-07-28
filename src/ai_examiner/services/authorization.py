from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..enterprise_constants import CAPABILITIES, ROLE_CAPABILITIES
from ..models import Organization, OrganizationMembership, Principal
from .authentication import CurrentAuthentication
from .oidc import AuthenticationContext
from .tenancy import set_tenant_context


class AuthorizationError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.public_message = message


@dataclass(frozen=True)
class AuthorizationContext:
    organization_id: str
    principal_id: str
    membership_id: str
    role: str
    capabilities: frozenset[str]
    authentication_method: str
    authorization_enforced: bool = True

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    def public_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "principal_id": self.principal_id,
            "membership_id": self.membership_id,
            "role": self.role,
            "capabilities": sorted(self.capabilities),
            "authentication_method": self.authentication_method,
            "authorization_enforced": self.authorization_enforced,
            "mode": "enforced",
        }


@dataclass(frozen=True)
class RoutePolicy:
    authentication: Literal["public", "conditional", "required"]
    capability: str | None
    resource_resolver: str
    audit: str

    def public_dict(self) -> dict:
        return {
            "authentication": self.authentication,
            "capability": self.capability,
            "resource_resolver": self.resource_resolver,
            "audit": self.audit,
        }


ROUTE_POLICIES: dict[tuple[str, str], RoutePolicy] = {
    ("GET", "/api/v1/context"): RoutePolicy(
        "conditional", None, "selected_organization", "none"
    ),
    ("GET", "/api/v1/auth/login"): RoutePolicy(
        "public", None, "none", "authentication"
    ),
    ("GET", "/api/v1/auth/callback"): RoutePolicy(
        "public", None, "oidc_login_transaction", "authentication"
    ),
    ("POST", "/api/v1/auth/logout"): RoutePolicy(
        "conditional", None, "browser_session", "authentication"
    ),
    ("GET", "/api/v1/me"): RoutePolicy(
        "conditional", None, "authenticated_principal", "none"
    ),
    ("GET", "/api/v1/system/capabilities"): RoutePolicy(
        "required", None, "authenticated_principal", "none"
    ),
    ("GET", "/api/v1/organizations/{organization_id}"): RoutePolicy(
        "required", "organization.read", "organization", "read"
    ),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/memberships",
    ): RoutePolicy("required", "member.read", "organization", "read_sensitive"),
    (
        "POST",
        "/api/v1/organizations/{organization_id}/memberships",
    ): RoutePolicy("required", "member.manage", "organization", "administrative"),
    (
        "PATCH",
        "/api/v1/organizations/{organization_id}/memberships/{membership_id}",
    ): RoutePolicy(
        "required",
        "member.manage",
        "organization_membership",
        "administrative",
    ),
    (
        "DELETE",
        "/api/v1/organizations/{organization_id}/memberships/{membership_id}",
    ): RoutePolicy(
        "required",
        "member.manage",
        "organization_membership",
        "administrative",
    ),
    ("GET", "/api/v1/documents/{document_id}/file"): RoutePolicy(
        "required", "document.read", "document", "read_sensitive"
    ),
    ("GET", "/api/v1/evidence/{asset_id}/file"): RoutePolicy(
        "required", "document.read", "evidence_asset", "read_sensitive"
    ),
    ("GET", "/api/v1/evidence/{asset_id}/highlight"): RoutePolicy(
        "required", "document.read", "evidence_asset", "read_sensitive"
    ),
    ("GET", "/api/v1/memory-exports/{artifact_id}/file"): RoutePolicy(
        "required",
        "learner_memory.admin",
        "memory_export_artifact",
        "read_sensitive",
    ),
    ("GET", "/api/v1/jobs/{job_id}"): RoutePolicy(
        "required", "job.read", "background_job", "read_sensitive"
    ),
    ("POST", "/api/v1/jobs/{job_id}/cancel"): RoutePolicy(
        "required", "job.manage", "background_job", "administrative"
    ),
    ("POST", "/api/v1/jobs/{job_id}/retry"): RoutePolicy(
        "required", "job.manage", "background_job", "administrative"
    ),
    ("GET", "/api/v1/organizations/{organization_id}/jobs"): RoutePolicy(
        "required", "job.read", "organization", "read_sensitive"
    ),
    (
        "POST",
        "/api/v1/organizations/{organization_id}/jobs/recover",
    ): RoutePolicy(
        "required", "job.manage", "organization", "administrative"
    ),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/model-policy",
    ): RoutePolicy("required", "policy.read", "organization", "read_sensitive"),
    (
        "PUT",
        "/api/v1/organizations/{organization_id}/model-policy",
    ): RoutePolicy("required", "policy.manage", "organization", "administrative"),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/quota",
    ): RoutePolicy("required", "policy.read", "organization", "read_sensitive"),
    (
        "PUT",
        "/api/v1/organizations/{organization_id}/quota",
    ): RoutePolicy("required", "policy.manage", "organization", "administrative"),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/usage",
    ): RoutePolicy("required", "usage.read", "organization", "read_sensitive"),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/usage/export",
    ): RoutePolicy("required", "usage.read", "organization", "read_sensitive"),
    ("GET", "/api/v1/organizations/{organization_id}/audit-events"): RoutePolicy(
        "required", "audit.read", "organization", "read_sensitive"
    ),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/audit-events/export",
    ): RoutePolicy(
        "required", "audit.read", "organization", "read_sensitive"
    ),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/retention-policy",
    ): RoutePolicy("required", "retention.read", "organization", "read_sensitive"),
    (
        "PUT",
        "/api/v1/organizations/{organization_id}/retention-policy",
    ): RoutePolicy(
        "required", "retention.manage", "organization", "administrative"
    ),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/legal-holds",
    ): RoutePolicy("required", "retention.read", "organization", "read_sensitive"),
    (
        "POST",
        "/api/v1/organizations/{organization_id}/legal-holds",
    ): RoutePolicy(
        "required", "retention.manage", "organization", "administrative"
    ),
    ("POST", "/api/v1/legal-holds/{hold_id}/release"): RoutePolicy(
        "required", "retention.manage", "legal_hold", "administrative"
    ),
    (
        "POST",
        "/api/v1/organizations/{organization_id}/exports",
    ): RoutePolicy(
        "required", "retention.manage", "organization", "administrative"
    ),
    ("GET", "/api/v1/organization-exports/{export_id}"): RoutePolicy(
        "required", "retention.manage", "organization_export", "read_sensitive"
    ),
    ("GET", "/api/v1/organization-exports/{export_id}/file"): RoutePolicy(
        "required", "retention.manage", "organization_export", "read_sensitive"
    ),
    (
        "POST",
        "/api/v1/organizations/{organization_id}/data-subject-requests",
    ): RoutePolicy(
        "required", "review_case.create", "organization", "administrative"
    ),
    ("GET", "/api/v1/data-subject-requests/{request_id}"): RoutePolicy(
        "required", "retention.read", "data_subject_request", "read_sensitive"
    ),
    ("POST", "/api/v1/data-subject-requests/{request_id}/approve"): RoutePolicy(
        "required", "retention.manage", "data_subject_request", "administrative"
    ),
    ("POST", "/api/v1/data-subject-requests/{request_id}/cancel"): RoutePolicy(
        "required", "retention.manage", "data_subject_request", "administrative"
    ),
    ("POST", "/api/v1/data-subject-requests/{request_id}/retry"): RoutePolicy(
        "required", "retention.manage", "data_subject_request", "administrative"
    ),
    (
        "POST",
        "/api/v1/organizations/{organization_id}/review-cases",
    ): RoutePolicy(
        "required", "review_case.create", "organization", "administrative"
    ),
    (
        "GET",
        "/api/v1/organizations/{organization_id}/review-cases",
    ): RoutePolicy(
        "required", "review_case.review", "organization", "read_sensitive"
    ),
    ("GET", "/api/v1/review-cases/{case_id}"): RoutePolicy(
        "required", "review_case.review", "review_case", "read_sensitive"
    ),
    ("POST", "/api/v1/review-cases/{case_id}/assign"): RoutePolicy(
        "required", "review_case.review", "review_case", "administrative"
    ),
    ("POST", "/api/v1/review-cases/{case_id}/decisions"): RoutePolicy(
        "required", "review_case.review", "review_case", "administrative"
    ),
    ("POST", "/api/v1/review-cases/{case_id}/appeals"): RoutePolicy(
        "required", "review_case.appeal", "review_case", "administrative"
    ),
}


def authorization_http_error(exc: AuthorizationError) -> HTTPException:
    headers = (
        {"WWW-Authenticate": "Bearer"}
        if exc.status_code == 401
        else None
    )
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.public_message},
        headers=headers,
    )


def effective_capabilities(role: str) -> frozenset[str]:
    capabilities = ROLE_CAPABILITIES.get(role)
    if capabilities is None:
        raise AuthorizationError(
            "authorization_denied",
            status_code=403,
            message="The requested operation is not permitted.",
        )
    return capabilities


def resolve_authenticated_principal(
    db: Session,
    *,
    authentication: AuthenticationContext,
    disabled_principal_id: str | None = None,
) -> Principal:
    settings = get_settings()
    principal_id = authentication.principal_id
    if (
        principal_id is None
        and settings.auth_mode == "disabled"
        and settings.app_env != "production"
    ):
        principal_id = disabled_principal_id
    if not principal_id:
        raise AuthorizationError(
            "authentication_required",
            status_code=401,
            message="Authentication is required.",
        )
    principal = db.get(Principal, principal_id)
    if principal is None or principal.status != "active":
        raise AuthorizationError(
            "authorization_denied",
            status_code=403,
            message="The requested operation is not permitted.",
        )
    return principal


def resolve_authorization_context(
    db: Session,
    *,
    authentication: AuthenticationContext,
    organization_id: str | None,
    required_capability: str | None,
    disabled_principal_id: str | None = None,
) -> AuthorizationContext:
    if required_capability is not None and required_capability not in CAPABILITIES:
        raise RuntimeError(f"Unknown capability: {required_capability}")
    if not organization_id:
        raise AuthorizationError(
            "organization_context_required",
            status_code=400,
            message="An organization context is required.",
        )
    principal = resolve_authenticated_principal(
        db,
        authentication=authentication,
        disabled_principal_id=disabled_principal_id,
    )
    set_tenant_context(
        db,
        organization_id=organization_id,
        principal_id=principal.id,
    )
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise AuthorizationError(
            "resource_not_found",
            status_code=404,
            message="The requested resource was not found.",
        )
    if organization.status != "active":
        raise AuthorizationError(
            "authorization_denied",
            status_code=403,
            message="The requested operation is not permitted.",
        )
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.principal_id == principal.id,
        )
    )
    if membership is None:
        raise AuthorizationError(
            "resource_not_found",
            status_code=404,
            message="The requested resource was not found.",
        )
    if membership.status != "active":
        raise AuthorizationError(
            "membership_inactive",
            status_code=403,
            message="The requested operation is not permitted.",
        )
    capabilities = effective_capabilities(membership.role)
    if required_capability is not None and required_capability not in capabilities:
        raise AuthorizationError(
            "authorization_denied",
            status_code=403,
            message="The requested operation is not permitted.",
        )
    return AuthorizationContext(
        organization_id=organization.id,
        principal_id=principal.id,
        membership_id=membership.id,
        role=membership.role,
        capabilities=capabilities,
        authentication_method=authentication.method,
    )


def authorize_resource_organization(
    context: AuthorizationContext,
    resource_organization_id: str | None,
) -> None:
    if (
        resource_organization_id is None
        or resource_organization_id != context.organization_id
    ):
        raise AuthorizationError(
            "resource_not_found",
            status_code=404,
            message="The requested resource was not found.",
        )


def require_capability(capability: str):
    if capability not in CAPABILITIES:
        raise RuntimeError(f"Unknown capability: {capability}")

    def dependency(
        request: Request,
        authentication: CurrentAuthentication,
        db: Annotated[Session, Depends(get_db)],
    ) -> AuthorizationContext:
        organization_id = request.path_params.get(
            "organization_id"
        ) or request.headers.get("X-AI-Examiner-Organization")
        try:
            context = resolve_authorization_context(
                db,
                authentication=authentication,
                organization_id=organization_id,
                required_capability=capability,
                disabled_principal_id=request.headers.get(
                    "X-AI-Examiner-Principal"
                ),
            )
            request.state.audit_actor_type = "principal"
            request.state.audit_actor_id = context.principal_id
            request.state.audit_authentication_method = (
                context.authentication_method
            )
            return context
        except AuthorizationError as exc:
            request.state.audit_reason_code = exc.code
            request.state.audit_actor_id = (
                authentication.principal_id
                or request.headers.get("X-AI-Examiner-Principal")
            )
            raise authorization_http_error(exc) from exc

    return dependency


def require_authenticated_principal(
    request: Request,
    authentication: CurrentAuthentication,
    db: Annotated[Session, Depends(get_db)],
) -> Principal:
    try:
        principal = resolve_authenticated_principal(
            db,
            authentication=authentication,
            disabled_principal_id=request.headers.get("X-AI-Examiner-Principal"),
        )
        request.state.audit_actor_type = "principal"
        request.state.audit_actor_id = principal.id
        request.state.audit_authentication_method = authentication.method
        return principal
    except AuthorizationError as exc:
        request.state.audit_reason_code = exc.code
        raise authorization_http_error(exc) from exc


def bind_and_validate_route_policies(app: FastAPI) -> None:
    discovered: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        for method in route.methods:
            key = (method, route.path)
            policy = ROUTE_POLICIES.get(key)
            if policy is None:
                raise RuntimeError(
                    f"Missing v0.9 route policy for {method} {route.path}"
                )
            discovered.add(key)
            route.openapi_extra = {
                **(route.openapi_extra or {}),
                "x-ai-examiner-policy": policy.public_dict(),
            }
    extra = set(ROUTE_POLICIES) - discovered
    if extra:
        formatted = ", ".join(f"{method} {path}" for method, path in sorted(extra))
        raise RuntimeError(f"Route policy has no matching API route: {formatted}")
