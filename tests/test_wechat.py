import hashlib
import io
import json
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from ai_examiner import wechat_api
from ai_examiner.config import get_settings
from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID
from ai_examiner.models import (
    AuditEvent,
    BrowserAuthSession,
    Organization,
    OrganizationMembership,
    Principal,
    utcnow,
)
from ai_examiner.services import wechat
from ai_examiner.services.oidc import OIDCAuthenticator, OIDCError
from ai_examiner.wechat_cli import approve


@pytest.fixture
def settings(monkeypatch):
    settings = get_settings()
    for name, value in dict(
        auth_mode="oidc",
        wechat_enabled=True,
        wechat_registration_mode="approval",
        wechat_app_id="wx-test",
        wechat_app_secret=SecretStr("fake-test-secret"),
    ).items():
        monkeypatch.setattr(settings, name, value)
    return settings


def active(db, settings):
    p = Principal(issuer=wechat.wechat_issuer(settings), subject="test-openid", status="active")
    db.add(p)
    db.commit()
    return p


def test_disabled_no_network(monkeypatch):
    monkeypatch.setattr(get_settings(), "wechat_enabled", False)
    with pytest.raises(OIDCError) as err:
        wechat.exchange_code(get_settings(), "unused")
    assert err.value.public_code == "dependency_unavailable"


@pytest.mark.parametrize(
    "payload",
    [
        {"openid": "test-openid", "session_key": "not-returned"},
        {"errcode": 40029},
        [],
        {"openid": ""},
    ],
)
def test_exchange_validates_and_discards_secret(settings, monkeypatch, payload):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    if isinstance(payload, dict) and payload.get("openid"):
        assert wechat.exchange_code(settings, "fake-code") == "test-openid"
    else:
        with pytest.raises(OIDCError):
            wechat.exchange_code(settings, "fake-code")


def test_exchange_errors_do_not_expose_url(settings, monkeypatch):
    opener = MagicMock()
    opener.open.side_effect = OSError("fake-test-secret query error")
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    with pytest.raises(OIDCError) as err:
        wechat.exchange_code(settings, "fake-code")
    assert "fake-test-secret" not in str(err.value)
    assert err.value.__suppress_context__


def test_pending_approval_hash_auth_logout(settings, monkeypatch):
    monkeypatch.setattr(wechat, "exchange_code", lambda *args: "test-openid")
    with SessionLocal() as db:
        with pytest.raises(OIDCError) as err:
            wechat.login(db, settings, "code")
        assert err.value.public_code == "authorization_denied"
        p = db.scalar(select(Principal))
        assert p.status == "pending"
        assert db.scalar(select(func.count()).select_from(OrganizationMembership)) == 0
        approve(db, settings, p.id, LEGACY_ORGANIZATION_ID, "test-operator")
        assert db.scalar(select(OrganizationMembership)).role == "examiner"
        assert db.scalar(select(AuditEvent)).action == "wechat.principal.approve"
        token = wechat.login(db, settings, "code")["access_token"]
        saved = db.scalar(select(BrowserAuthSession))
        assert saved.session_token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert saved.session_token_hash != token
        assert wechat.authenticate(db, settings, token).principal_id == p.id
        OIDCAuthenticator(settings).revoke_session(db, token)
        with pytest.raises(OIDCError):
            wechat.authenticate(db, settings, token)


@pytest.mark.parametrize("reason", ["idle", "expired", "disabled", "wrong_app", "suspended"])
def test_session_boundaries(settings, monkeypatch, reason):
    monkeypatch.setattr(wechat, "exchange_code", lambda *args: "test-openid")
    with SessionLocal() as db:
        p = active(db, settings)
        token = wechat.login(db, settings, "code")["access_token"]
        saved = db.scalar(select(BrowserAuthSession))
        if reason == "idle":
            saved.last_seen_at = utcnow() - timedelta(minutes=121)
        if reason == "expired":
            saved.expires_at = utcnow() - timedelta(seconds=1)
        if reason == "disabled":
            monkeypatch.setattr(settings, "wechat_enabled", False)
        if reason == "wrong_app":
            monkeypatch.setattr(settings, "wechat_app_id", "another-app")
        if reason == "suspended":
            p.status = "suspended"
        db.commit()
        with pytest.raises(OIDCError):
            wechat.authenticate(db, settings, token)


def test_http_login_identity_and_rbac(client, settings, monkeypatch):
    monkeypatch.setattr(wechat_api, "check_login_capacity", lambda *_: None)
    monkeypatch.setattr(wechat, "exchange_code", lambda *args: "test-openid")
    assert (
        client.post("/api/v1/wechat/login", json={"code": "x", "openid": "spoof"}).status_code
        == 422
    )
    with SessionLocal() as db:
        active(db, settings)
    response = client.post("/api/v1/wechat/login", json={"code": "x"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    token = response.json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["organizations"] == []
    assert me.json()["authentication"]["method"] == "wechat_session"
    assert client.get(
        "/api/projects", headers={**headers, "X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID}
    ).status_code in {403, 404}
    assert client.post("/api/v1/wechat/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_rate_gate_fail_closed_and_limits(settings, monkeypatch):
    from redis.exceptions import RedisError

    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **k: conn)
    conn.eval.return_value = 1
    wechat.check_login_capacity(settings)
    conn.eval.return_value = 31
    with pytest.raises(OIDCError) as err:
        wechat.check_login_capacity(settings)
    assert err.value.public_code == "rate_limited"
    conn.eval.side_effect = RedisError("not available")
    with pytest.raises(OIDCError) as err:
        wechat.check_login_capacity(settings)
    assert err.value.public_code == "dependency_unavailable"


def test_mini_program_api_contract_complete_text_flow(client, settings, monkeypatch):
    """Protocol regression only: simulated WeChat and deterministic LLM, not quality eval."""
    from ai_examiner.services.jobs import dispatch_job_by_id

    monkeypatch.setattr(wechat_api, "check_login_capacity", lambda *_: None)
    monkeypatch.setattr(wechat, "exchange_code", lambda *args: "test-openid")
    with SessionLocal() as db:
        p = Principal(
            issuer=wechat.wechat_issuer(settings), subject="test-openid", status="pending"
        )
        db.add(p)
        db.commit()
        approve(db, settings, p.id, LEGACY_ORGANIZATION_ID, "test-admin")
    token = client.post("/api/v1/wechat/login", json={"code": "x"}).json()["access_token"]
    client.headers.update(
        {"Authorization": "Bearer " + token, "X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID}
    )
    project_response = client.post("/api/projects", json={"name": "Mini-program protocol test"})
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()
    uploaded = client.post(
        f"/api/projects/{project['id']}/documents",
        files={
            "file": (
                "paper.txt",
                b"We compare two baselines. The method uses calibrated evidence. Limitations include small sample size.",
                "text/plain",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    monkeypatch.setattr("ai_examiner.main.dispatch_job_by_id", lambda *_: None)
    job_response = client.post(
        f"/api/projects/{project['id']}/blueprints/async",
        json={
            "document_id": uploaded.json()["id"],
            "profile": "mock:heuristic-v2",
            "mode": "defense",
        },
        headers={"Idempotency-Key": "wx-protocol-test"},
    )
    assert job_response.status_code == 202, job_response.text
    dispatch_job_by_id(job_response.json()["id"])
    job = client.get("/api/v1/jobs/" + job_response.json()["id"]).json()
    assert job["status"] == "completed", job
    session_response = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": job["result"]["blueprint"]["id"],
            "profile": "mock:heuristic-v2",
            "question_limit": 1,
            "max_followups": 0,
            "question_strategy": "adaptive",
        },
    )
    assert session_response.status_code == 201, session_response.text
    sid = session_response.json()["id"]
    assert client.post(f"/api/sessions/{sid}/start").status_code == 200
    answer = client.post(
        f"/api/sessions/{sid}/answers",
        json={
            "answer": "We used two controlled baselines; the small sample limits generalization."
        },
    )
    assert answer.status_code == 200, answer.text
    current = client.get(f"/api/sessions/{sid}").json()
    for _ in range(20):
        if current["status"] == "completed":
            break
        response = client.post(
            f"/api/sessions/{sid}/answers",
            json={
                "answer": "The evidence compares two baselines with controlled conditions. We acknowledge sample size limits and uncertainty."
            },
        )
        assert response.status_code == 200, response.text
        current = client.get(f"/api/sessions/{sid}").json()
    assert current["status"] == "completed"
    assert len(current["turns"]) >= 3
    report = client.get(f"/api/sessions/{sid}/report")
    assert report.status_code == 200, report.text
    assert "priority_weaknesses" in report.json()


def test_disabled_wechat_cannot_bypass_using_browser_cookie(client, settings, monkeypatch):
    monkeypatch.setattr(wechat, "exchange_code", lambda *args: "test-openid")
    with SessionLocal() as db:
        active(db, settings)
        token = wechat.login(db, settings, "code")["access_token"]
    monkeypatch.setattr(settings, "wechat_enabled", False)
    client.cookies.set(settings.oidc_session_cookie_name, token)
    assert client.get('/api/v1/me').status_code == 503


def test_public_status_has_no_secrets_and_reports_configuration(client, settings, monkeypatch):
    response = client.get('/api/v1/wechat/status')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json() == {
        'state': 'ready', 'login_available': True, 'app_id': 'wx-test',
        'registration_mode': 'approval',
    }
    assert 'fake-test-secret' not in response.text
    monkeypatch.setattr(settings, 'wechat_app_secret', None)
    assert client.get('/api/v1/wechat/status').json()['state'] == 'missing_credentials'
    monkeypatch.setattr(settings, 'wechat_enabled', False)
    assert client.get('/api/v1/wechat/status').json() == {
        'state': 'disabled', 'login_available': False, 'app_id': None,
        'registration_mode': None,
    }


@pytest.fixture
def personal_settings(settings, monkeypatch):
    monkeypatch.setattr(settings, 'wechat_registration_mode', 'personal')
    monkeypatch.setattr(wechat, 'exchange_code', lambda *args: 'personal-openid')
    return settings


@pytest.mark.parametrize('already_pending', [False, True])
def test_personal_login_provisions_once_and_audits(personal_settings, already_pending):
    from ai_examiner.services.tenancy import current_tenant_context

    with SessionLocal() as db:
        if already_pending:
            db.add(Principal(
                issuer=wechat.wechat_issuer(personal_settings), subject='personal-openid',
                status='pending',
            ))
            db.commit()
        previous = current_tenant_context(db)
        first = wechat.login(db, personal_settings, 'code')
        second = wechat.login(db, personal_settings, 'another-code')
        assert first['access_token'] != second['access_token']
        p = db.scalar(select(Principal))
        assert p.status == 'active'
        membership = db.scalars(select(OrganizationMembership)).one()
        assert membership.principal_id == p.id
        assert membership.organization_id == wechat.personal_space_id(p)
        assert (membership.role, membership.status) == ('examiner', 'active')
        organization = db.get(Organization, membership.organization_id)
        assert organization.display_name == '我的个人空间'
        assert organization.id != LEGACY_ORGANIZATION_ID
        events = db.scalars(select(AuditEvent)).all()
        assert len(events) == 2
        assert {e.action for e in events} == {
            'organization.create', 'wechat.principal.self_register',
        }
        assert all(e.organization_id == organization.id for e in events)
        assert current_tenant_context(db) == previous
        assert wechat.authenticate(db, personal_settings, first['access_token']).principal_id == p.id


@pytest.mark.parametrize('status', ['suspended', 'disabled'])
def test_personal_registration_never_reactivates_account(personal_settings, status):
    with SessionLocal() as db:
        p = Principal(
            issuer=wechat.wechat_issuer(personal_settings), subject='personal-openid', status=status,
        )
        db.add(p)
        db.commit()
        with pytest.raises(OIDCError):
            wechat.login(db, personal_settings, 'code')
        assert p.status == status
        assert db.scalar(select(func.count()).select_from(BrowserAuthSession)) == 0
        assert db.scalar(select(func.count()).select_from(OrganizationMembership)) == 0


@pytest.mark.parametrize('membership_status', ['active', 'suspended', 'revoked'])
def test_personal_mode_preserves_existing_authorization(personal_settings, membership_status):
    with SessionLocal() as db:
        p = Principal(
            issuer=wechat.wechat_issuer(personal_settings), subject='personal-openid', status='active',
        )
        db.add(p)
        db.flush()
        db.add(OrganizationMembership(
            organization_id=LEGACY_ORGANIZATION_ID, principal_id=p.id,
            role='learner', status=membership_status,
        ))
        db.commit()
        wechat.login(db, personal_settings, 'code')
        m = db.scalars(select(OrganizationMembership)).one()
        assert (m.organization_id, m.role, m.status) == (
            LEGACY_ORGANIZATION_ID, 'learner', membership_status,
        )
        assert db.get(Organization, wechat.personal_space_id(p)) is None
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_personal_space_collision_is_not_adopted(personal_settings):
    with SessionLocal() as db:
        p = Principal(
            issuer=wechat.wechat_issuer(personal_settings), subject='personal-openid', status='pending',
        )
        db.add(p)
        db.flush()
        db.add(Organization(
            id=wechat.personal_space_id(p), slug='preexisting', display_name='Existing',
        ))
        db.commit()
        with pytest.raises(OIDCError):
            wechat.login(db, personal_settings, 'code')
        assert db.get(Principal, p.id).status == 'pending'
        assert db.scalar(select(func.count()).select_from(OrganizationMembership)) == 0
        assert db.scalar(select(func.count()).select_from(BrowserAuthSession)) == 0


def test_personal_registration_rolls_back_on_audit_failure(personal_settings, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('test audit failure')

    monkeypatch.setattr(wechat, 'append_audit_event', fail)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match='test audit failure'):
            wechat.login(db, personal_settings, 'code')
        assert db.scalar(select(Principal)).status == 'pending'
        assert db.scalar(select(func.count()).select_from(Organization)) == 1  # legacy only
        assert db.scalar(select(func.count()).select_from(OrganizationMembership)) == 0
        assert db.scalar(select(func.count()).select_from(BrowserAuthSession)) == 0


def test_personal_provisioning_requires_current_app_and_opt_in(settings, monkeypatch):
    with SessionLocal() as db:
        p = Principal(issuer='wechat:miniprogram:other-app', subject='test', status='pending')
        db.add(p)
        db.commit()
        with pytest.raises(ValueError):
            wechat.ensure_personal_space(db, settings, p.id)
        monkeypatch.setattr(settings, 'wechat_registration_mode', 'personal')
        with pytest.raises(OIDCError):
            wechat.ensure_personal_space(db, settings, p.id)
        assert p.status == 'pending'


def test_personal_http_accounts_cannot_share_or_spoof_spaces(client, personal_settings, monkeypatch):
    monkeypatch.setattr(wechat_api, 'check_login_capacity', lambda *_: None)
    monkeypatch.setattr(wechat, 'exchange_code', lambda settings, code: 'verified-' + code)
    assert client.get('/api/v1/wechat/status').json()['registration_mode'] == 'personal'
    headers, organizations, projects, documents = [], [], [], []
    for name in ['alpha', 'beta']:
        response = client.post('/api/v1/wechat/login', json={'code': name})
        assert response.status_code == 200, response.text
        auth = {'Authorization': 'Bearer ' + response.json()['access_token']}
        me = client.get('/api/v1/me', headers=auth)
        assert me.status_code == 200, me.text
        spaces = me.json()['organizations']
        assert len(spaces) == 1
        oid = spaces[0]['id']
        organizations.append(oid)
        headers.append({**auth, 'X-AI-Examiner-Organization': oid})
        created = client.post('/api/projects', headers=headers[-1], json={'name': name})
        assert created.status_code == 201, created.text
        projects.append(created.json()['id'])
        uploaded = client.post(
            f'/api/projects/{projects[-1]}/documents', headers=headers[-1],
            files={'file': ('private.txt', b'Private non-sensitive test evidence.', 'text/plain')},
        )
        assert uploaded.status_code == 201, uploaded.text
        documents.append(uploaded.json()['id'])
    assert organizations[0] != organizations[1]
    for index in range(2):
        visible = client.get('/api/projects', headers=headers[index])
        assert visible.status_code == 200
        assert [p['id'] for p in visible.json()] == [projects[index]]
        denied = client.get(
            f'/api/projects/{projects[1-index]}/documents', headers=headers[index],
        )
        assert denied.status_code == 404
        assert client.get(
            f'/api/documents/{documents[1-index]}/evidence', headers=headers[index],
        ).status_code == 404
        forged = {**headers[index], 'X-AI-Examiner-Organization': organizations[1-index]}
        assert client.get('/api/projects', headers=forged).status_code in {403, 404}
    assert client.post('/api/v1/wechat/login', json={
        'code': 'spoof', 'organization_id': organizations[0], 'role': 'owner',
    }).status_code == 422
