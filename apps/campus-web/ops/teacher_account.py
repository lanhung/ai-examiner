"""Operator-only teacher provisioning for an exact campus password username."""
import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, UUID, uuid5


class Refused(Exception):
    pass


def web_account(path, username):
    if not re.fullmatch(r"[a-zA-Z0-9_]{3,32}", username):
        raise Refused("Invalid web username")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT id, username, active FROM accounts WHERE username = ?",
                          (username.lower(),)).fetchall()
    if len(rows) != 1 or not rows[0][2]:
        raise Refused("No unique active web account matched this username")
    return {"id": str(UUID(rows[0][0])), "username": rows[0][1]}


def teacher_account(db, account, *, apply=False):
    from sqlalchemy import select
    from identity_bridge import IdentityBridge, ISSUER
    from ai_examiner.models import Organization, OrganizationMembership, Principal, TeachingGrant
    from ai_examiner.school_api import require_school_principal, school_me
    from ai_examiner.services.membership_admin import MembershipAdministrationService
    from ai_examiner.services.tenancy import set_tenant_context
    from ai_examiner.teaching_cli import grant_teacher

    bridge = IdentityBridge()
    pid, student_org = bridge._ids(account)
    teacher_org = str(uuid5(NAMESPACE_URL, ISSUER + ":teacher:" + pid))
    set_tenant_context(db, organization_id=None, principal_id=pid)
    query = select(Principal).where(Principal.id == pid)
    principal = db.scalar(query.with_for_update() if apply else query)
    if not principal:
        raise Refused("Web account exists but has not completed its first sign-in")
    if (principal.issuer, principal.subject, principal.status) != (ISSUER, account["id"], "active"):
        raise Refused("Business identity does not match the active web account")
    require_school_principal(principal)
    bridge._space(db, principal, student_org)
    set_tenant_context(db, organization_id=None, principal_id=pid)
    existing = db.get(TeachingGrant, pid)
    current = school_me(principal, db)
    result = {"username": account["username"], "identity": "campus_password", "student_space": "active",
              "teacher": current["teacher"], "separate_teacher_space": bool(current["teacher"] and
                  current["teacher_organization_id"] != student_org), "changed": False}
    if existing and existing.organization_id != teacher_org:
        if existing.active and result["separate_teacher_space"]:
            return result
        raise Refused("Existing teacher assignment conflicts; no migration or reactivation performed")
    if not apply or result["teacher"]:
        return result
    if existing:
        raise Refused("A teacher grant already exists but is inactive or unusable; manual review required")
    set_tenant_context(db, organization_id=teacher_org, principal_id=pid)
    if db.get(Organization, teacher_org) or db.scalar(select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == teacher_org)):
        raise Refused("Expected empty dedicated teacher space; refusing to adopt an existing organization")
    db.add(Organization(id=teacher_org, slug="campus-teacher-" + pid,
                        display_name="我的教师空间", status="active"))
    db.flush()
    MembershipAdministrationService(db).create(organization_id=teacher_org, principal_id=pid,
        role="examiner", status="active", commit=False)
    # This official operation commits the new space, membership, grant and audit together.
    grant_teacher(db, pid, teacher_org, active=True, operator="campus-operator")
    confirmed = school_me(principal, db)
    if not confirmed["teacher"] or confirmed["teacher_organization_id"] != teacher_org:
        raise Refused("Grant verification failed; inspect the audit before retrying")
    return {**result, "teacher": True, "separate_teacher_space": True, "changed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    account = web_account(Path("/var/lib/examiner-campus-web/accounts.sqlite3"), args.username)
    root = Path("/opt/examiner-campus-web")
    sys.path[:0] = [str(root), "/opt/ai-examiner/src"]
    runtime = json.loads(Path("/etc/ai-examiner/runtime.json").read_text())
    for key in ("DATABASE_URL", "AUTH_MODE", "APP_ENV", "DATABASE_SCHEMA_MANAGEMENT", "POSTGRES_RLS_MODE",
                "AUDIT_IP_HASH_KEY", "SCHOOL_RESTRICTED_PRINCIPAL_IDS"):
        if key in runtime:
            os.environ[key] = str(runtime[key]) if not isinstance(runtime[key], list) else json.dumps(runtime[key])
    del runtime
    if not os.environ.get("DATABASE_URL"):
        raise Refused("No explicit business database is configured")
    if args.apply:
        import pwd
        from sqlalchemy.engine import URL, make_url
        target = make_url(os.environ["DATABASE_URL"])
        if (target.get_backend_name() != "postgresql" or target.host not in ("127.0.0.1", "localhost")
                or not target.database):
            raise Refused("Apply requires the existing same-host PostgreSQL operator connection")
        os.environ["DATABASE_URL"] = str(URL.create("postgresql+psycopg", username="postgres",
            database=target.database, query={"host": "/var/run/postgresql", "port": str(target.port or 5432)}))
        del target
        # Same peer-authenticated local operator as the repository's deployment tools.
        # No database passwords are passed to a child or written to disk.
        pg = pwd.getpwnam("postgres")
        os.chdir("/tmp")
        os.setgroups([])
        os.setgid(pg.pw_gid)
        os.setuid(pg.pw_uid)
    with TemporaryDirectory(prefix="campus-operator-") as scratch:
        for key in ("UPLOAD_DIR", "EVIDENCE_DIR", "EXPORT_DIR", "BACKUP_DIR", "STORAGE_LOCAL_ROOT", "PROMPT_DIR"):
            os.environ[key] = str(Path(scratch) / key.lower())
        from ai_examiner.db import SessionLocal
        from sqlalchemy.exc import SQLAlchemyError
        try:
            with SessionLocal() as db:
                print(json.dumps(teacher_account(db, account, apply=args.apply)))
        except SQLAlchemyError as exc:
            state = getattr(getattr(exc, "orig", None), "sqlstate", None)
            raise Refused("Database operation failed: " + type(exc).__name__ + " SQLSTATE=" + str(state)) from None


if __name__ == "__main__":
    try:
        main()
    except Refused as exc:
        raise SystemExit(str(exc)) from None
