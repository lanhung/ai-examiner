from __future__ import annotations

from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID
from ai_examiner.models import DataSubjectRequest, Project
from ai_examiner.services.authentication import get_oidc_authenticator
from ai_examiner.services.enterprise_identity import bootstrap_owner
from ai_examiner.services.oidc import AuthenticationContext


def _owner(subject: str) -> str:
    with SessionLocal() as db:
        _organization, principal, _membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject=subject,
            display_name="Enterprise Owner",
        )
        return principal.id


def _headers(principal_id: str) -> dict[str, str]:
    return {
        "X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID,
        "X-AI-Examiner-Principal": principal_id,
    }


def test_enterprise_console_is_a_dedicated_operational_surface(client):
    response = client.get("/enterprise")

    assert response.status_code == 200
    html = response.text
    assert "AI Examiner 企业控制台" in html
    assert "成员与权限" in html
    assert "模型治理" in html
    assert "审计日志" in html
    assert "数据保留" in html
    assert "人工复核" in html
    assert "/static/enterprise.js?v=0.9.0-wp13-loginfix3" in html

    script = client.get("/static/enterprise.js?v=0.9.0-wp13-loginfix3")
    assert script.status_code == 200
    assert "abortOrganizationRequests" in script.text
    assert "capturedOrganization !== state.organizationId" in script.text
    assert "X-AI-Examiner-Organization" in script.text
    assert "new Set(context.capabilities || [])" in script.text
    assert "Object.assign(organization, context.organization)" in script.text
    assert 'item.status !== "revoked"' in script.text
    assert 'isDelete ? "DELETE" : "APPROVE"' in script.text
    assert "function showLoginRequired()" in script.text
    assert "function isOidcAuthMethod(method)" in script.text
    assert "isOidcAuthMethod(state.authMethod)" in script.text
    assert "error instanceof ApiError && error.status === 401" in script.text
    assert "if (response.status === 401) showLoginRequired();" in script.text
    stylesheet = client.get("/static/enterprise.css?v=0.9.0-wp13")
    assert stylesheet.status_code == 200
    assert ".organization-picker span { display: none; }" in stylesheet.text


def test_me_response_includes_organization_identity_for_switcher():
    owner_id = _owner("enterprise-ui-switcher")

    with SessionLocal() as db:
        response = get_oidc_authenticator().me(
            db,
            AuthenticationContext(
                method="oidc",
                principal_id=owner_id,
                issuer="https://issuer.example.test",
                subject="enterprise-ui-switcher",
                scopes=frozenset({"openid"}),
            ),
        )

    organization = response["organizations"][0]
    assert organization["id"] == LEGACY_ORGANIZATION_ID
    assert organization["display_name"]
    assert organization["slug"]
    assert organization["status"] == "active"
    assert organization["role"] == "owner"


def test_data_subject_request_list_is_filtered_and_tenant_scoped(client):
    owner_id = _owner("enterprise-ui-lifecycle")
    with SessionLocal() as db:
        export_project = Project(
            organization_id=LEGACY_ORGANIZATION_ID,
            name="UI export target",
            domain="research_defense",
            language="zh-CN",
        )
        delete_project = Project(
            organization_id=LEGACY_ORGANIZATION_ID,
            name="UI delete target",
            domain="research_defense",
            language="zh-CN",
        )
        db.add_all([export_project, delete_project])
        db.flush()
        db.add_all(
            [
                DataSubjectRequest(
                    organization_id=LEGACY_ORGANIZATION_ID,
                    request_type="export",
                    target_type="project",
                    target_id=export_project.id,
                    requester_principal_id=owner_id,
                    idempotency_key="enterprise-ui-export",
                    status="completed",
                ),
                DataSubjectRequest(
                    organization_id=LEGACY_ORGANIZATION_ID,
                    request_type="delete",
                    target_type="project",
                    target_id=delete_project.id,
                    requester_principal_id=owner_id,
                    idempotency_key="enterprise-ui-delete",
                    status="requested",
                ),
            ]
        )
        db.commit()

    response = client.get(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            "/data-subject-requests?status=requested&request_type=delete"
        ),
        headers=_headers(owner_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["request_type"] == "delete"
    assert payload["items"][0]["status"] == "requested"
    assert all(
        item["organization_id"] == LEGACY_ORGANIZATION_ID
        for item in payload["items"]
    )


def test_data_subject_request_list_rejects_invalid_filter(client):
    owner_id = _owner("enterprise-ui-invalid-filter")
    response = client.get(
        (
            f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}"
            "/data-subject-requests?status=all-data"
        ),
        headers=_headers(owner_id),
    )

    assert response.status_code == 422
