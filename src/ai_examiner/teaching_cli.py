"""Explicit teacher grants, run with the database administration credential."""

import argparse
from uuid import uuid4

from sqlalchemy import select

from .db import SessionLocal
from .models import Organization, OrganizationMembership, Principal, TeachingGrant, utcnow
from .services.audit import append_audit_event
from .services.tenancy import set_tenant_context


def grant_teacher(db, principal_id: str, organization_id: str, *, active: bool, operator: str):
    set_tenant_context(db, organization_id=organization_id, principal_id=principal_id)
    principal = db.get(Principal, principal_id)
    organization = db.get(Organization, organization_id)
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.principal_id == principal_id,
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.status == "active",
        OrganizationMembership.role.in_(["owner", "admin", "examiner"]),
    ))
    if not principal or principal.status != "active" or not organization or (
        organization.status != "active" or not membership
    ):
        raise ValueError("An active account with an existing examiner/admin/owner membership is required")
    grant = db.get(TeachingGrant, principal_id)
    if grant and grant.organization_id != organization_id:
        raise ValueError("Moving a teacher to another workspace requires a separate migration")
    if not grant:
        grant = TeachingGrant(principal_id=principal_id, organization_id=organization_id)
        db.add(grant)
    grant.active = active
    grant.updated_at = utcnow()
    append_audit_event(
        db, organization_id=organization_id, actor_type="system", actor_id=operator,
        authentication_method="server_cli", action="school.teacher.grant" if active else "school.teacher.revoke",
        resource_type="principal", resource_id=principal_id, outcome="succeeded",
        reason_code="operator_approved", request_id=str(uuid4()), trace_id=uuid4().hex,
    )
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--revoke", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("Teacher can publish materials and access submitted grades; require --confirm")
    with SessionLocal() as db:
        grant_teacher(db, args.principal_id, args.organization_id, active=not args.revoke, operator=args.operator)
    print("Teacher grant updated. No organization membership or administrator rights changed.")


if __name__ == "__main__":
    main()
