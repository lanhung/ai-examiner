from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enterprise_constants import (
    LEGACY_ORGANIZATION_ID,
    LEGACY_ORGANIZATION_NAME,
    LEGACY_ORGANIZATION_SLUG,
    MEMBERSHIP_STATUSES,
    ORGANIZATION_ROLES,
    PRINCIPAL_STATUSES,
)
from ..models import Organization, OrganizationMembership, Principal, utcnow


class EnterpriseIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class OrganizationContext:
    organization_id: str
    principal_id: str | None
    principal_status: str | None
    membership_id: str | None
    membership_status: str | None
    role: str | None
    source: str
    authorization_enforced: bool = False

    def public_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "principal_id": self.principal_id,
            "principal_status": self.principal_status,
            "membership_id": self.membership_id,
            "membership_status": self.membership_status,
            "role": self.role,
            "source": self.source,
            "authorization_enforced": self.authorization_enforced,
            "mode": "observe_only",
        }


def ensure_legacy_organization(db: Session) -> Organization:
    organization = db.get(Organization, LEGACY_ORGANIZATION_ID)
    if organization is None:
        organization = Organization(
            id=LEGACY_ORGANIZATION_ID,
            slug=LEGACY_ORGANIZATION_SLUG,
            display_name=LEGACY_ORGANIZATION_NAME,
            status="active",
        )
        db.add(organization)
        db.flush()
    return organization


def bootstrap_owner(
    db: Session,
    *,
    issuer: str,
    subject: str,
    display_name: str | None = None,
    email: str | None = None,
    organization_id: str = LEGACY_ORGANIZATION_ID,
) -> tuple[Organization, Principal, OrganizationMembership]:
    issuer = issuer.strip()
    subject = subject.strip()
    if not issuer or not subject:
        raise EnterpriseIdentityError("issuer and subject are required")

    organization = db.get(Organization, organization_id)
    if organization is None and organization_id == LEGACY_ORGANIZATION_ID:
        organization = ensure_legacy_organization(db)
    if organization is None:
        raise EnterpriseIdentityError("organization does not exist")
    if organization.status != "active":
        raise EnterpriseIdentityError("organization is not active")

    principal = db.scalar(
        select(Principal).where(
            Principal.issuer == issuer,
            Principal.subject == subject,
        )
    )
    if principal is None:
        principal = Principal(
            issuer=issuer,
            subject=subject,
            display_name=display_name,
            email=email,
            status="active",
        )
        db.add(principal)
        db.flush()
    elif principal.status != "active":
        raise EnterpriseIdentityError(
            f"existing principal is not active: {principal.status}"
        )
    else:
        if display_name and not principal.display_name:
            principal.display_name = display_name
        if email and not principal.email:
            principal.email = email

    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.principal_id == principal.id,
        )
    )
    if membership is None:
        membership = OrganizationMembership(
            organization_id=organization.id,
            principal_id=principal.id,
            role="owner",
            status="active",
        )
        db.add(membership)
    elif membership.role != "owner" or membership.status != "active":
        raise EnterpriseIdentityError(
            "existing membership is not an active owner membership"
        )

    db.commit()
    db.refresh(organization)
    db.refresh(principal)
    db.refresh(membership)
    return organization, principal, membership


def transition_principal_status(
    db: Session,
    principal: Principal,
    target_status: str,
) -> Principal:
    if target_status not in PRINCIPAL_STATUSES:
        raise EnterpriseIdentityError("unknown principal status")
    allowed = {
        "pending": {"active", "disabled"},
        "active": {"suspended", "disabled"},
        "suspended": {"active", "disabled"},
        "disabled": set(),
    }
    if target_status == principal.status:
        return principal
    if target_status not in allowed[principal.status]:
        raise EnterpriseIdentityError(
            f"invalid principal status transition: {principal.status} -> {target_status}"
        )
    principal.status = target_status
    principal.updated_at = utcnow()
    principal.disabled_at = utcnow() if target_status == "disabled" else None
    db.commit()
    db.refresh(principal)
    return principal


def resolve_organization_context(
    db: Session,
    *,
    requested_organization_id: str | None = None,
    requested_principal_id: str | None = None,
) -> OrganizationContext:
    ensure_legacy_organization(db)
    db.commit()
    organization_id = requested_organization_id or LEGACY_ORGANIZATION_ID
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise EnterpriseIdentityError("organization context does not exist")

    if not requested_principal_id:
        return OrganizationContext(
            organization_id=organization.id,
            principal_id=None,
            principal_status=None,
            membership_id=None,
            membership_status=None,
            role=None,
            source="legacy_default" if not requested_organization_id else "disabled_header",
        )

    principal = db.get(Principal, requested_principal_id)
    membership = None
    if principal is not None:
        membership = db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization.id,
                OrganizationMembership.principal_id == principal.id,
            )
        )
    return OrganizationContext(
        organization_id=organization.id,
        principal_id=principal.id if principal is not None else None,
        principal_status=principal.status if principal is not None else None,
        membership_id=membership.id if membership is not None else None,
        membership_status=membership.status if membership is not None else None,
        role=(
            membership.role
            if principal is not None
            and principal.status == "active"
            and membership is not None
            and membership.status == "active"
            else None
        ),
        source="disabled_header",
    )


def organization_context(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> OrganizationContext:
    try:
        return resolve_organization_context(
            db,
            requested_organization_id=request.headers.get(
                "X-AI-Examiner-Organization"
            ),
            requested_principal_id=request.headers.get("X-AI-Examiner-Principal"),
        )
    except EnterpriseIdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def serialize_organization(organization: Organization) -> dict:
    return {
        "id": organization.id,
        "slug": organization.slug,
        "display_name": organization.display_name,
        "status": organization.status,
        "version": organization.version,
        "created_at": organization.created_at.isoformat(),
        "updated_at": organization.updated_at.isoformat(),
    }


def serialize_principal(principal: Principal) -> dict:
    return {
        "id": principal.id,
        "issuer": principal.issuer,
        "subject": principal.subject,
        "display_name": principal.display_name,
        "email": principal.email,
        "status": principal.status,
        "created_at": principal.created_at.isoformat(),
        "updated_at": principal.updated_at.isoformat(),
        "disabled_at": (
            principal.disabled_at.isoformat() if principal.disabled_at else None
        ),
    }


def serialize_membership(membership: OrganizationMembership) -> dict:
    if membership.role not in ORGANIZATION_ROLES:
        raise EnterpriseIdentityError("membership contains an unknown role")
    if membership.status not in MEMBERSHIP_STATUSES:
        raise EnterpriseIdentityError("membership contains an unknown status")
    return {
        "id": membership.id,
        "organization_id": membership.organization_id,
        "principal_id": membership.principal_id,
        "role": membership.role,
        "status": membership.status,
        "version": membership.version,
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat(),
    }
