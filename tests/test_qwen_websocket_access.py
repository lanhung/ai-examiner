from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect
from test_realtime_voice_v04 import create_project_and_blueprint

from ai_examiner.db import SessionLocal
from ai_examiner.main import settings
from ai_examiner.models import (
    BrowserAuthSession,
    ModelUsageLedger,
    Organization,
    OrganizationMembership,
    Principal,
    VoiceSession,
)
from ai_examiner.services.enterprise_identity import bootstrap_owner
from ai_examiner.services.tenancy import current_tenant_context


class QwenTransport:
    def __init__(self, error=None):
        self.configured = asyncio.Event()
        self.sent = []
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def send(self, message):
        self.sent.append(json.loads(message))
        self.configured.set()

    async def events(self):
        yield json.dumps({"type": "session.created"})
        await self.configured.wait()
        if self.error:
            yield json.dumps({"type": "error", "error": {"message": self.error}})
            return
        yield json.dumps({"type": "session.updated"})
        await asyncio.Future()

    def __aiter__(self):
        return self.events()


@pytest.fixture
def voice_access(client, monkeypatch):
    project, blueprint = create_project_and_blueprint(client)
    voice = client.post("/api/voice/sessions", json={
        "project_id": project["id"], "blueprint_id": blueprint["id"], "provider": "qwen",
    }).json()
    now = datetime.now(UTC)
    cookie = "test-only-voice-browser-session"
    with SessionLocal() as db:
        org, principal, membership = bootstrap_owner(
            db, issuer="https://issuer.example.test", subject="voice-owner",
        )
        browser = BrowserAuthSession(
            principal_id=principal.id, session_token_hash=hashlib.sha256(cookie.encode()).hexdigest(),
            auth_time=now, expires_at=now + timedelta(hours=1),
        )
        db.add(browser)
        db.commit()
        identifiers = (org.id, principal.id, membership.id, browser.id)
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "http://testserver/api/v1/auth/callback")
    client.cookies.set(settings.oidc_session_cookie_name, cookie)
    org_id, principal_id, membership_id, browser_id = identifiers
    return {
        "voice": voice, "org_id": org_id, "principal_id": principal_id,
        "membership_id": membership_id, "browser_id": browser_id,
        "path": f"/api/voice/sessions/{voice['id']}/qwen-ws?organization_id={org_id}",
        "headers": {"Origin": "http://testserver"},
    }


@pytest.mark.parametrize("denial", [
    "anonymous", "expired", "revoked", "inactive_principal", "inactive_membership",
    "missing_capability", "inactive_org", "other_org", "foreign_voice", "missing_org",
    "missing_origin", "foreign_origin", "completed", "production_no_auth",
])
def test_qwen_denies_before_paid_connection(client, monkeypatch, voice_access, denial):
    item = voice_access
    path, headers = item["path"], dict(item["headers"])
    calls = []
    monkeypatch.setattr("ai_examiner.main.websockets.connect", lambda *a, **kw: calls.append(a))
    with SessionLocal() as db:
        if denial == "anonymous":
            client.cookies.clear()
        elif denial == "expired":
            db.get(BrowserAuthSession, item["browser_id"]).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif denial == "revoked":
            db.get(BrowserAuthSession, item["browser_id"]).revoked_at = datetime.now(UTC)
        elif denial == "inactive_principal":
            db.get(Principal, item["principal_id"]).status = "disabled"
        elif denial == "inactive_membership":
            db.get(OrganizationMembership, item["membership_id"]).status = "revoked"
        elif denial == "missing_capability":
            db.get(OrganizationMembership, item["membership_id"]).role = "reviewer"
        elif denial == "inactive_org":
            db.get(Organization, item["org_id"]).status = "suspended"
        elif denial in {"other_org", "foreign_voice"}:
            other = Organization(slug="other-voice", display_name="Other", status="active")
            db.add(other)
            db.flush()
            if denial == "other_org":
                path = path.split("?")[0] + f"?organization_id={other.id}"
            else:
                db.get(VoiceSession, item["voice"]["id"]).organization_id = other.id
        elif denial == "missing_org":
            path = path.split("?")[0]
        elif denial == "missing_origin":
            headers.clear()
        elif denial == "foreign_origin":
            headers["Origin"] = "https://attacker.example"
        elif denial == "completed":
            db.get(VoiceSession, item["voice"]["id"]).status = "completed"
        elif denial == "production_no_auth":
            monkeypatch.setattr(settings, "auth_mode", "disabled")
            monkeypatch.setattr(settings, "app_env", "production")
        db.commit()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path, headers=headers):
            pass
    assert exc.value.code == 1008
    assert not calls
    with SessionLocal() as db:
        assert not db.scalars(select(ModelUsageLedger).where(ModelUsageLedger.task_type == "voice")).all()


def test_qwen_cookie_auth_binds_every_voice_lookup_and_waits_for_model(client, monkeypatch, voice_access):
    item = voice_access
    upstream = QwenTransport()
    monkeypatch.setattr("ai_examiner.main.websockets.connect", lambda *a, **kw: upstream)
    lookups = []

    def guard(execution):
        mapper = execution.bind_arguments.get("mapper")
        if mapper is not None and mapper.class_ is VoiceSession:
            tenant = current_tenant_context(execution.session)
            assert tenant.organization_id == item["org_id"]
            assert tenant.principal_id == item["principal_id"]
            lookups.append(tenant)

    event.listen(Session, "do_orm_execute", guard)
    try:
        with client.websocket_connect(item["path"], headers=item["headers"]) as socket:
            assert socket.receive_json()["type"] == "session.created"
            # A successful WebSocket handshake must not settle the model call.
            with SessionLocal() as db:
                usage = db.scalar(select(ModelUsageLedger).where(ModelUsageLedger.task_type == "voice"))
                assert usage.status == "reserved"
            socket.send_json(item["voice"]["client_config"])
            assert socket.receive_json()["type"] == "session.updated"
    finally:
        event.remove(Session, "do_orm_execute", guard)
    assert len(lookups) >= 2
    with SessionLocal() as db:
        voice = db.get(VoiceSession, item["voice"]["id"])
        assert voice.started_at is not None
        assert voice.status == "connected"
        usage = db.scalar(select(ModelUsageLedger).where(ModelUsageLedger.task_type == "voice"))
        assert usage.status == "completed"
        assert usage.actor_principal_id == item["principal_id"]


def test_qwen_model_rejection_keeps_session_unstarted_and_fails_ledger(client, monkeypatch, voice_access):
    upstream = QwenTransport(error="Model not exist. secret-do-not-expose")
    monkeypatch.setattr("ai_examiner.main.websockets.connect", lambda *a, **kw: upstream)
    item = voice_access
    with client.websocket_connect(item["path"], headers=item["headers"]) as socket:
        assert socket.receive_json()["type"] == "session.created"
        socket.send_json(item["voice"]["client_config"])
        error = socket.receive_json()
        assert error["error"]["code"] == "qwen_model_unavailable"
        assert "secret-do-not-expose" not in str(error)
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    with SessionLocal() as db:
        assert db.get(VoiceSession, item["voice"]["id"]).started_at is None
        usage = db.scalar(select(ModelUsageLedger).where(ModelUsageLedger.task_type == "voice"))
        assert usage.status == "failed"


def test_qwen_revocation_closes_live_connection(client, monkeypatch, voice_access):
    upstream = QwenTransport()
    monkeypatch.setattr("ai_examiner.main.websockets.connect", lambda *a, **kw: upstream)
    item = voice_access
    with client.websocket_connect(item["path"], headers=item["headers"]) as socket:
        assert socket.receive_json()["type"] == "session.created"
        socket.send_json(item["voice"]["client_config"])
        assert socket.receive_json()["type"] == "session.updated"
        with SessionLocal() as db:
            db.get(BrowserAuthSession, item["browser_id"]).revoked_at = datetime.now(UTC)
            db.commit()
        error = socket.receive_json()
        assert error["error"]["code"] == "voice_access_expired"
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
