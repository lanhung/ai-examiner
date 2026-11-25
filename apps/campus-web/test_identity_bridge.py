"""Uses a disposable SQLite database, never the runtime PostgreSQL credentials."""
import os
from pathlib import Path
import sys
import tempfile

import pytest
from fastapi import HTTPException

_tmp=tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"]="sqlite:///"+str(Path(_tmp.name)/"business.sqlite3").replace("\\","/")
os.environ["AUTH_MODE"]="oidc"
os.environ["APP_ENV"]="development"
os.environ["DATABASE_SCHEMA_MANAGEMENT"]="external"
_here = Path(__file__).resolve().parent
for _src in (_here.parent.parent / "src", _here.parent / "ai-examiner" / "src"):
    if (_src / "ai_examiner" / "db.py").is_file():
        sys.path.insert(0, str(_src))
        break
from identity_bridge import IdentityBridge, ISSUER
from ai_examiner.db import Base,engine,SessionLocal
from ai_examiner.models import Principal,OrganizationMembership,TeachingGrant,AuditEvent
from sqlalchemy import select
from uuid import uuid4


@pytest.fixture(scope="module",autouse=True)
def cleanup():
    yield
    from ai_examiner.db import audit_engine
    engine.dispose();audit_engine.dispose();_tmp.cleanup()


def test_registration_isolated_student_only():
    Base.metadata.create_all(engine)
    bridge=IdentityBridge()
    a={"id":str(uuid4()),"nickname":"Synthetic A"}
    b={"id":str(uuid4()),"nickname":"Synthetic B"}
    ta,tb=bridge.issue(a),bridge.issue(b)
    oa,ob=bridge.workspace(ta,"student"),bridge.workspace(tb,"student")
    assert oa!=ob
    assert bridge.workspace(bridge.issue(a),"student")==oa
    with SessionLocal() as db:
        pa=db.get(Principal,bridge._ids(a)[0])
        assert pa.issuer==ISSUER and pa.subject==a["id"]
        assert not db.get(TeachingGrant,pa.id)
        assert db.scalar(select(AuditEvent).where(AuditEvent.actor_id==pa.id))
        membership=db.scalar(select(OrganizationMembership).where(OrganizationMembership.principal_id==pa.id))
        membership.status="revoked";db.commit()
    with pytest.raises(HTTPException):bridge.workspace(ta,"student")
    with pytest.raises(HTTPException):bridge.issue(a)
    with pytest.raises(HTTPException):bridge.workspace(tb,"teacher")
    bridge.revoke(tb)
    with pytest.raises(HTTPException):bridge.workspace(tb,"student")


def test_teacher_provision_is_exact_separate_and_idempotent(tmp_path):
    from ops.teacher_account import teacher_account, web_account, Refused
    from passwords import PasswordStore
    from sqlalchemy import func
    Base.metadata.create_all(engine)
    store = PasswordStore(tmp_path/"accounts.sqlite3")
    teacher = store.register("teacher_fixture", "same nickname", "a temporary passphrase")
    student = store.register("student_fixture", "teacher_fixture", "another temporary passphrase")
    target = web_account(store.path, "TEACHER_FIXTURE")
    assert target["id"] == teacher["id"] != student["id"]
    with pytest.raises(Refused):
        web_account(store.path, "missing")
    bridge = IdentityBridge()
    tokens = [bridge.issue(a) for a in (teacher, student)]
    original = bridge.workspace(tokens[0], "student")
    with SessionLocal() as db:
        assert not teacher_account(db, target)["teacher"]
        assert teacher_account(db, target, apply=True)["changed"]
        assert not teacher_account(db, target, apply=True)["changed"]
        principal_id = bridge._ids(target)[0]
        roles = db.scalars(select(OrganizationMembership.role).where(
            OrganizationMembership.principal_id == principal_id)).all()
        assert sorted(roles) == ["examiner", "examiner"]
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "school.teacher.grant", AuditEvent.resource_id == principal_id)) == 1
    assert bridge.workspace(tokens[0], "student") == original
    assert bridge.workspace(tokens[0], "teacher") != original
    with pytest.raises(HTTPException):
        bridge.workspace(tokens[1], "teacher")
    with store.connect() as db:
        db.execute("UPDATE accounts SET active=0 WHERE id=?", (target["id"],))
    with pytest.raises(Refused):
        web_account(store.path, "teacher_fixture")
