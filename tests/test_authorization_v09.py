from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from ai_examiner.config import Settings
from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import (
    CAPABILITIES,
    HIGH_RISK_CAPABILITIES,
    LEGACY_ORGANIZATION_ID,
    ORGANIZATION_ROLES,
    ROLE_CAPABILITIES,
)
from ai_examiner.main import app
from ai_examiner.models import Organization, OrganizationMembership, Principal
from ai_examiner.services.authorization import (
    ROUTE_POLICIES,
    AuthorizationContext,
    AuthorizationError,
    authorize_resource_organization,
    resolve_authorization_context,
)
from ai_examiner.services.enterprise_identity import bootstrap_owner
from ai_examiner.services.oidc import AuthenticationContext
from ai_examiner.services.template_access import template_authoring_context


def authentication(principal_id: str | None, *, method: str = "disabled"):
    return AuthenticationContext(
        method=method,
        principal_id=principal_id,
        issuer=None,
        subject=None,
        scopes=frozenset(),
    )


def create_organization(db, slug: str, status: str = "active") -> Organization:
    organization = Organization(
        slug=slug,
        display_name=f"{slug.title()} Organization",
        status=status,
    )
    db.add(organization)
    db.flush()
    return organization


def create_principal(
    db,
    subject: str,
    *,
    status: str = "active",
) -> Principal:
    principal = Principal(
        issuer="https://issuer.example.test",
        subject=subject,
        display_name=subject,
        status=status,
    )
    db.add(principal)
    db.flush()
    return principal


def add_membership(
    db,
    organization: Organization,
    principal: Principal,
    *,
    role: str,
    status: str = "active",
) -> OrganizationMembership:
    membership = OrganizationMembership(
        organization_id=organization.id,
        principal_id=principal.id,
        role=role,
        status=status,
    )
    db.add(membership)
    db.flush()
    return membership


def disabled_headers(
    organization_id: str,
    principal_id: str,
) -> dict[str, str]:
    return {
        "X-AI-Examiner-Organization": organization_id,
        "X-AI-Examiner-Principal": principal_id,
    }


def test_role_registry_is_complete_and_uses_only_registered_capabilities():
    assert set(ROLE_CAPABILITIES) == set(ORGANIZATION_ROLES)
    assert CAPABILITIES
    assert HIGH_RISK_CAPABILITIES <= CAPABILITIES
    assert all(bundle <= CAPABILITIES for bundle in ROLE_CAPABILITIES.values())
    assert ROLE_CAPABILITIES["owner"] == CAPABILITIES
    assert "member.grant_owner" not in ROLE_CAPABILITIES["admin"]
    assert "template.publish" not in ROLE_CAPABILITIES["reviewer"]
    assert "learner_memory.manage_self" in ROLE_CAPABILITIES["learner"]


def test_every_v1_route_has_bound_policy_metadata(client):
    discovered = {}
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        for method in route.methods:
            policy = route.openapi_extra["x-ai-examiner-policy"]
            discovered[(method, route.path)] = policy

    assert set(discovered) == set(ROUTE_POLICIES)
    for key, policy in ROUTE_POLICIES.items():
        assert discovered[key] == policy.public_dict()

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    capability_operation = openapi.json()["paths"][
        "/api/v1/organizations/{organization_id}/memberships"
    ]["get"]
    assert capability_operation["x-ai-examiner-policy"]["capability"] == "member.read"


def test_capability_catalog_requires_active_principal(client):
    with SessionLocal() as db:
        principal = create_principal(db, "catalog-reader")
        db.commit()
        principal_id = principal.id

    anonymous = client.get("/api/v1/system/capabilities")
    authenticated = client.get(
        "/api/v1/system/capabilities",
        headers={"X-AI-Examiner-Principal": principal_id},
    )

    assert anonymous.status_code == 401
    assert authenticated.status_code == 200
    assert set(authenticated.json()["capabilities"]) == set(CAPABILITIES)
    assert authenticated.json()["roles"]["owner"] == sorted(CAPABILITIES)


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        ("owner", "organization.delete", None),
        ("admin", "member.manage", "member.grant_owner"),
        ("examiner", "session.conduct", "member.read"),
        ("template_author", "template.author", "template.publish"),
        ("reviewer", "template.review", "template.publish"),
        ("learner", "learner_memory.manage_self", "project.create"),
        ("auditor", "audit.read", "member.manage"),
    ],
)
def test_role_capability_matrix_is_enforced(role, allowed, denied):
    with SessionLocal() as db:
        organization = create_organization(db, f"role-{role.replace('_', '-')}")
        principal = create_principal(db, f"{role}-principal")
        add_membership(db, organization, principal, role=role)
        db.commit()

        context = resolve_authorization_context(
            db,
            authentication=authentication(principal.id),
            organization_id=organization.id,
            required_capability=allowed,
            disabled_principal_id=principal.id,
        )
        assert context.role == role
        assert context.can(allowed)

        if denied:
            with pytest.raises(AuthorizationError) as captured:
                resolve_authorization_context(
                    db,
                    authentication=authentication(principal.id),
                    organization_id=organization.id,
                    required_capability=denied,
                    disabled_principal_id=principal.id,
                )
            assert captured.value.code == "authorization_denied"


def test_same_role_in_other_organization_is_denied():
    with SessionLocal() as db:
        organization_a = create_organization(db, "tenant-a")
        organization_b = create_organization(db, "tenant-b")
        principal_a = create_principal(db, "examiner-a")
        principal_b = create_principal(db, "examiner-b")
        add_membership(db, organization_a, principal_a, role="examiner")
        add_membership(db, organization_b, principal_b, role="examiner")
        db.commit()

        with pytest.raises(AuthorizationError) as captured:
            resolve_authorization_context(
                db,
                authentication=authentication(principal_a.id),
                organization_id=organization_b.id,
                required_capability="project.read",
                disabled_principal_id=principal_a.id,
            )

    assert captured.value.code == "resource_not_found"
    assert captured.value.status_code == 404


@pytest.mark.parametrize(
    ("principal_status", "membership_status", "organization_status"),
    [
        ("suspended", "active", "active"),
        ("disabled", "active", "active"),
        ("active", "suspended", "active"),
        ("active", "revoked", "active"),
        ("active", "active", "suspended"),
    ],
)
def test_inactive_security_subjects_are_denied(
    principal_status,
    membership_status,
    organization_status,
):
    with SessionLocal() as db:
        organization = create_organization(
            db,
            f"inactive-{principal_status}-{membership_status}-{organization_status}",
            status=organization_status,
        )
        principal = create_principal(db, "inactive-user", status=principal_status)
        add_membership(
            db,
            organization,
            principal,
            role="owner",
            status=membership_status,
        )
        db.commit()

        with pytest.raises(AuthorizationError):
            resolve_authorization_context(
                db,
                authentication=authentication(principal.id),
                organization_id=organization.id,
                required_capability="organization.read",
                disabled_principal_id=principal.id,
            )


def test_resource_organization_mismatch_returns_not_found():
    context = AuthorizationContext(
        organization_id="organization-a",
        principal_id="principal-a",
        membership_id="membership-a",
        role="owner",
        capabilities=ROLE_CAPABILITIES["owner"],
        authentication_method="oidc_bearer",
    )

    with pytest.raises(AuthorizationError) as captured:
        authorize_resource_organization(context, "organization-b")

    assert captured.value.status_code == 404
    assert captured.value.code == "resource_not_found"


def test_anonymous_and_capability_denials_on_membership_api(client):
    with SessionLocal() as db:
        organization = create_organization(db, "membership-denials")
        examiner = create_principal(db, "examiner-denied")
        add_membership(db, organization, examiner, role="examiner")
        db.commit()
        organization_id = organization.id
        examiner_id = examiner.id

    anonymous = client.get(
        f"/api/v1/organizations/{organization_id}/memberships"
    )
    denied = client.get(
        f"/api/v1/organizations/{organization_id}/memberships",
        headers=disabled_headers(organization_id, examiner_id),
    )

    assert anonymous.status_code == 401
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "authorization_denied"


def test_membership_api_denies_cross_organization_actor_and_resource(client):
    with SessionLocal() as db:
        organization_a = create_organization(db, "api-tenant-a")
        organization_b = create_organization(db, "api-tenant-b")
        admin_a = create_principal(db, "api-admin-a")
        admin_b = create_principal(db, "api-admin-b")
        membership_a = add_membership(
            db,
            organization_a,
            admin_a,
            role="admin",
        )
        membership_b = add_membership(
            db,
            organization_b,
            admin_b,
            role="admin",
        )
        db.commit()
        organization_a_id = organization_a.id
        organization_b_id = organization_b.id
        admin_a_id = admin_a.id
        membership_b_id = membership_b.id
        assert membership_a.id

    foreign_actor = client.get(
        f"/api/v1/organizations/{organization_b_id}/memberships",
        headers=disabled_headers(organization_b_id, admin_a_id),
    )
    foreign_resource = client.patch(
        (
            f"/api/v1/organizations/{organization_a_id}"
            f"/memberships/{membership_b_id}"
        ),
        headers={
            **disabled_headers(organization_a_id, admin_a_id),
            "If-Match": '"1"',
        },
        json={"role": "reviewer"},
    )

    assert foreign_actor.status_code == 404
    assert foreign_actor.json()["detail"]["code"] == "resource_not_found"
    assert foreign_resource.status_code == 404
    assert foreign_resource.json()["detail"]["code"] == "resource_not_found"


def test_membership_administration_uses_etag_and_terminal_revocation(client):
    with SessionLocal() as db:
        _organization, owner, _owner_membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject="membership-owner",
        )
        target = create_principal(db, "membership-target")
        db.commit()
        owner_id = owner.id
        target_id = target.id

    headers = disabled_headers(LEGACY_ORGANIZATION_ID, owner_id)
    created = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/memberships",
        headers=headers,
        json={"principal_id": target_id, "role": "examiner", "status": "active"},
    )
    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    membership_id = created.json()["id"]

    missing_precondition = client.patch(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{membership_id}"
        ),
        headers=headers,
        json={"role": "reviewer"},
    )
    assert missing_precondition.status_code == 428

    stale = client.patch(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{membership_id}"
        ),
        headers={**headers, "If-Match": '"9"'},
        json={"role": "reviewer"},
    )
    assert stale.status_code == 412

    updated = client.patch(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{membership_id}"
        ),
        headers={**headers, "If-Match": '"1"'},
        json={"role": "reviewer"},
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == '"2"'
    assert updated.json()["role"] == "reviewer"

    revoked = client.delete(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{membership_id}"
        ),
        headers={**headers, "If-Match": '"2"'},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.headers["etag"] == '"3"'

    terminal = client.patch(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{membership_id}"
        ),
        headers={**headers, "If-Match": '"3"'},
        json={"status": "active"},
    )
    assert terminal.status_code == 409
    assert terminal.json()["detail"]["code"] == "membership_transition_invalid"


def test_admin_cannot_grant_or_modify_owner_membership(client):
    with SessionLocal() as db:
        organization, owner, owner_membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject="protected-owner",
        )
        admin = create_principal(db, "membership-admin")
        target = create_principal(db, "prospective-owner")
        add_membership(db, organization, admin, role="admin")
        db.commit()
        admin_id = admin.id
        target_id = target.id
        owner_membership_id = owner_membership.id

    headers = disabled_headers(LEGACY_ORGANIZATION_ID, admin_id)
    grant = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/memberships",
        headers=headers,
        json={"principal_id": target_id, "role": "owner", "status": "active"},
    )
    modify = client.patch(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{owner_membership_id}"
        ),
        headers={**headers, "If-Match": '"1"'},
        json={"role": "admin"},
    )

    assert grant.status_code == 403
    assert modify.status_code == 403
    assert grant.json()["detail"]["code"] == "authorization_denied"


def test_last_active_owner_cannot_be_revoked(client):
    with SessionLocal() as db:
        _organization, owner, owner_membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject="last-owner",
        )
        db.commit()
        owner_id = owner.id
        membership_id = owner_membership.id

    response = client.delete(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{membership_id}"
        ),
        headers={
            **disabled_headers(LEGACY_ORGANIZATION_ID, owner_id),
            "If-Match": '"1"',
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "last_owner_required"


def test_owner_can_grant_second_owner_then_demote_first(client):
    with SessionLocal() as db:
        _organization, first_owner, first_membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject="first-owner",
        )
        second_owner = create_principal(db, "second-owner")
        db.commit()
        first_owner_id = first_owner.id
        first_membership_id = first_membership.id
        second_owner_id = second_owner.id

    headers = disabled_headers(LEGACY_ORGANIZATION_ID, first_owner_id)
    grant = client.post(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/memberships",
        headers=headers,
        json={
            "principal_id": second_owner_id,
            "role": "owner",
            "status": "active",
        },
    )
    demote = client.patch(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            f"/memberships/{first_membership_id}"
        ),
        headers={**headers, "If-Match": '"1"'},
        json={"role": "admin"},
    )

    assert grant.status_code == 201
    assert demote.status_code == 200
    assert demote.json()["role"] == "admin"


def test_template_authoring_seam_uses_oidc_capabilities(monkeypatch):
    from ai_examiner.services import template_access as template_access_module

    monkeypatch.setattr(
        template_access_module,
        "get_settings",
        lambda: Settings(
            app_env="test",
            auth_mode="oidc",
            oidc_issuer_url="http://localhost:9100",
            oidc_audience="api",
            oidc_client_id="client",
            oidc_redirect_uri="http://localhost/callback",
            auth_session_secret="test-session-secret",
            oidc_allow_insecure_http=True,
        ),
    )
    with SessionLocal() as db:
        organization = create_organization(db, "template-auth")
        author = create_principal(db, "template-author")
        learner = create_principal(db, "template-learner")
        add_membership(db, organization, author, role="template_author")
        add_membership(db, organization, learner, role="learner")
        db.commit()

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/templates",
                "headers": [
                    (
                        b"x-ai-examiner-organization",
                        organization.id.encode("ascii"),
                    )
                ],
            }
        )
        author_context = template_authoring_context(
            request,
            replace(
                authentication(author.id, method="oidc_bearer"),
                issuer="https://issuer.example.test",
            ),
            db,
        )
        assert author_context.authorization_enforced is True
        assert author_context.can("template.author")

        with pytest.raises(HTTPException) as denied:
            template_authoring_context(
                request,
                replace(
                    authentication(learner.id, method="oidc_bearer"),
                    issuer="https://issuer.example.test",
                ),
                db,
            )
        assert denied.value.status_code == 403
