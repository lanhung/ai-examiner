"""Run only on a unique disposable schema clone, never on the serving database.

No provider calls, user materials or real browser credentials are used.
"""
import hashlib
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, WebSocket
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from ai_examiner.config import get_settings
from ai_examiner.db import SessionLocal, engine
from ai_examiner.models import (
    Blueprint,
    BrowserAuthSession,
    Document,
    ExamSession,
    OrganizationMembership,
    Principal,
    Project,
    VoiceSession,
)
from ai_examiner.services.tenancy import set_tenant_context
from ai_examiner.services.voice_access import authorized_qwen_voice
from ai_examiner.services.wechat import ensure_personal_space, personal_space_id, wechat_issuer


def verify():
    settings = get_settings()
    name = make_url(settings.database_url).database or ""
    assert engine.dialect.name == "postgresql"
    assert re.fullmatch(r"aiex_qwen_web_[a-f0-9]{32}_test", name), "Refusing non-disposable DB"
    assert settings.oidc_redirect_uri == "https://voice.example.test/callback"
    fixtures = []
    for _ in range(2):
        with SessionLocal() as db:
            role = db.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
            assert not role.rolsuper and not role.rolbypassrls
            assert db.scalar(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.voice_sessions'::regclass"))
            principal = Principal(issuer=wechat_issuer(settings), subject="synthetic-" + uuid4().hex, status="pending")
            db.add(principal)
            db.commit()
            org_id = personal_space_id(principal)
            assert ensure_personal_space(db, settings, principal.id) == org_id
            db.commit()
            set_tenant_context(db, organization_id=org_id, principal_id=principal.id)
            project = Project(organization_id=org_id, name="Synthetic Qwen RLS check")
            db.add(project)
            db.flush()
            document = Document(organization_id=org_id, project_id=project.id, filename="synthetic.txt", content_type="text/plain", content_text="Synthetic evidence only")
            db.add(document)
            db.flush()
            blueprint = Blueprint(organization_id=org_id, project_id=project.id, document_id=document.id, data={}, provider="test", model="test")
            db.add(blueprint)
            db.flush()
            exam = ExamSession(organization_id=org_id, project_id=project.id, blueprint_id=blueprint.id)
            db.add(exam)
            db.flush()
            voice = VoiceSession(organization_id=org_id, project_id=project.id, blueprint_id=blueprint.id, exam_session_id=exam.id, provider="qwen", model=settings.qwen_realtime_model, voice="Cherry")
            token = "synthetic-" + uuid4().hex
            browser = BrowserAuthSession(principal_id=principal.id, session_token_hash=hashlib.sha256(token.encode()).hexdigest(), auth_time=datetime.now(UTC), expires_at=datetime.now(UTC) + timedelta(hours=1))
            db.add_all([voice, browser])
            db.commit()
            fixtures.append((principal.id, org_id, voice.id, token))

    pid, org_id, voice_id, token = fixtures[0]
    other_voice = fixtures[1][2]

    async def unused_transport(*_args):
        raise AssertionError("This check must not use a network transport")

    def connection(selected_org=org_id):
        return WebSocket({
            "type": "websocket", "scheme": "wss", "path": "/qwen-ws",
            "query_string": f"organization_id={selected_org}".encode(),
            "headers": [(b"origin", b"https://voice.example.test"), (b"cookie", f"{settings.oidc_session_cookie_name}={token}".encode())],
            "server": ("voice.example.test", 443),
        }, receive=unused_transport, send=unused_transport)

    with SessionLocal() as db:
        assert db.get(VoiceSession, voice_id) is None
    with SessionLocal() as db:
        voice = authorized_qwen_voice(connection(), db, voice_id, settings)
        voice.status = "connected"
        db.commit()
        db.expire_all()
        assert db.get(VoiceSession, voice_id).status == "connected"
        assert db.get(VoiceSession, other_voice) is None
    for selected, requested in [(org_id, other_voice), (fixtures[1][1], voice_id)]:
        with SessionLocal() as db:
            try:
                authorized_qwen_voice(connection(selected), db, requested, settings)
            except HTTPException as error:
                assert error.status_code in {403, 404}
            else:
                raise AssertionError("Cross-tenant voice access accepted")
    with SessionLocal() as db:
        set_tenant_context(db, organization_id=org_id, principal_id=pid)
        membership = db.scalar(select(OrganizationMembership).where(OrganizationMembership.principal_id == pid))
        membership.status = "revoked"
        db.commit()
    with SessionLocal() as db:
        try:
            authorized_qwen_voice(connection(), db, voice_id, settings)
        except HTTPException as error:
            assert error.status_code in {403, 404}
        else:
            raise AssertionError("Revoked voice membership accepted")
    engine.dispose()
    print("PASS: FORCE RLS, cookie authentication, tenant lookup/update after commit, cross-tenant denial, revoked membership")


if __name__ == "__main__":
    verify()
