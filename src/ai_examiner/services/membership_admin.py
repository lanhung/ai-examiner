from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enterprise_constants import MEMBERSHIP_STATUSES, ORGANIZATION_ROLES
from ..models import OrganizationMembership, Principal, utcnow


class MembershipAdministrationError(RuntimeError):
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


class MembershipAdministrationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, organization_id: str) -> list[OrganizationMembership]:
        return list(
            self.db.scalars(
                select(OrganizationMembership)
                .where(OrganizationMembership.organization_id == organization_id)
                .order_by(
                    OrganizationMembership.created_at,
                    OrganizationMembership.id,
                )
            ).all()
        )

    def create(
        self,
        *,
        organization_id: str,
        principal_id: str,
        role: str,
        status: str,
    ) -> OrganizationMembership:
        self._validate_role_and_status(role, status)
        principal = self.db.get(Principal, principal_id)
        if principal is None or principal.status in {"suspended", "disabled"}:
            raise MembershipAdministrationError(
                "principal_unavailable",
                status_code=422,
                message="The selected principal cannot receive membership.",
            )
        existing = self.db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.principal_id == principal_id,
            )
        )
        if existing is not None:
            raise MembershipAdministrationError(
                "membership_exists",
                status_code=409,
                message="A membership already exists for this principal.",
            )
        membership = OrganizationMembership(
            organization_id=organization_id,
            principal_id=principal_id,
            role=role,
            status=status,
        )
        self.db.add(membership)
        self.db.commit()
        self.db.refresh(membership)
        return membership

    def update(
        self,
        membership: OrganizationMembership,
        *,
        expected_version: int,
        role: str | None,
        status: str | None,
    ) -> OrganizationMembership:
        if membership.version != expected_version:
            raise MembershipAdministrationError(
                "membership_version_conflict",
                status_code=412,
                message="The membership has changed. Reload and retry.",
            )
        target_role = role or membership.role
        target_status = status or membership.status
        self._validate_role_and_status(target_role, target_status)
        self._validate_status_transition(membership.status, target_status)
        self._protect_last_owner(
            membership,
            target_role=target_role,
            target_status=target_status,
        )
        membership.role = target_role
        membership.status = target_status
        membership.version += 1
        membership.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(membership)
        return membership

    def revoke(
        self,
        membership: OrganizationMembership,
        *,
        expected_version: int,
    ) -> OrganizationMembership:
        return self.update(
            membership,
            expected_version=expected_version,
            role=None,
            status="revoked",
        )

    def get_in_organization(
        self,
        *,
        organization_id: str,
        membership_id: str,
    ) -> OrganizationMembership:
        membership = self.db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.id == membership_id,
                OrganizationMembership.organization_id == organization_id,
            )
        )
        if membership is None:
            raise MembershipAdministrationError(
                "resource_not_found",
                status_code=404,
                message="The requested resource was not found.",
            )
        return membership

    @staticmethod
    def _validate_role_and_status(role: str, status: str) -> None:
        if role not in ORGANIZATION_ROLES:
            raise MembershipAdministrationError(
                "membership_role_invalid",
                status_code=422,
                message="The membership role is invalid.",
            )
        if status not in MEMBERSHIP_STATUSES:
            raise MembershipAdministrationError(
                "membership_status_invalid",
                status_code=422,
                message="The membership status is invalid.",
            )

    @staticmethod
    def _validate_status_transition(current: str, target: str) -> None:
        if current == target:
            return
        allowed = {
            "invited": {"active", "revoked"},
            "active": {"suspended", "revoked"},
            "suspended": {"active", "revoked"},
            "revoked": set(),
        }
        if target not in allowed[current]:
            raise MembershipAdministrationError(
                "membership_transition_invalid",
                status_code=409,
                message="The membership status transition is invalid.",
            )

    def _protect_last_owner(
        self,
        membership: OrganizationMembership,
        *,
        target_role: str,
        target_status: str,
    ) -> None:
        remains_active_owner = target_role == "owner" and target_status == "active"
        currently_active_owner = (
            membership.role == "owner" and membership.status == "active"
        )
        if not currently_active_owner or remains_active_owner:
            return
        owners = list(
            self.db.scalars(
                select(OrganizationMembership)
                .where(
                    OrganizationMembership.organization_id
                    == membership.organization_id,
                    OrganizationMembership.role == "owner",
                    OrganizationMembership.status == "active",
                )
                .with_for_update()
            ).all()
        )
        if len(owners) <= 1:
            raise MembershipAdministrationError(
                "last_owner_required",
                status_code=409,
                message="The organization must retain at least one active owner.",
            )
