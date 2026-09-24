"""Privileged, explicit approval of an existing pending mini-program principal."""

from __future__ import annotations

import argparse
from uuid import uuid4

from .config import get_settings
from .db import SessionLocal
from .models import Organization, Principal, utcnow
from .services.audit import append_audit_event
from .services.membership_admin import MembershipAdministrationService
from .services.tenancy import set_tenant_context
from .services.wechat import require_wechat, wechat_issuer


def approve(db, settings, principal_id: str, organization_id: str, operator: str):
    require_wechat(settings)
    set_tenant_context(db, organization_id=organization_id, principal_id=None)
    principal = db.get(Principal, principal_id)
    organization = db.get(Organization, organization_id)
    if (
        principal is None
        or principal.issuer != wechat_issuer(settings)
        or principal.status != "pending"
    ):
        raise ValueError("Only a pending principal for the configured WeChat app can be approved")
    if organization is None or organization.status != "active":
        raise ValueError("Active organization required")
    principal.status = "active"
    principal.updated_at = utcnow()
    MembershipAdministrationService(db).create(
        organization_id=organization_id,
        principal_id=principal_id,
        role="examiner",
        status="active",
        commit=False,
    )
    append_audit_event(
        db,
        organization_id=organization_id,
        actor_type="system",
        actor_id=operator,
        authentication_method="server_cli",
        action="wechat.principal.approve",
        resource_type="principal",
        resource_id=principal_id,
        outcome="succeeded",
        reason_code="operator_approved",
        request_id=str(uuid4()),
        trace_id=uuid4().hex,
        metadata={"role": "examiner"},
        settings=settings,
    )
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--operator", required=True, help="Recorded administrator identifier")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("Approval grants examiner access to organization projects; require --confirm")
    with SessionLocal() as db:
        approve(db, get_settings(), args.principal_id, args.organization_id, args.operator)
    print("Approved pending account with examiner role; no owner/admin rights granted.")


if __name__ == "__main__":
    main()
