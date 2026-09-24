"""Run ONLY against a disposable schema clone with a non-bypass PostgreSQL role.

The database name must start with aiex_wechat_personal_ and end with _test.
This creates synthetic identities and never exchanges WeChat codes or issues tokens.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from ai_examiner.config import get_settings
from ai_examiner.db import SessionLocal, engine
from ai_examiner.models import AuditEvent, Organization, OrganizationMembership, Principal, Project
from ai_examiner.services.tenancy import set_tenant_context
from ai_examiner.services.wechat import ensure_personal_space, personal_space_id, wechat_issuer


def verify():
    settings = get_settings()
    name = make_url(settings.database_url).database or ''
    if engine.dialect.name != 'postgresql' or not (
        name.startswith('aiex_wechat_personal_') and name.endswith('_test')
    ):
        raise RuntimeError('Refusing non-disposable database')
    with SessionLocal() as db:
        role = db.execute(text(
            'SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user'
        )).one()
        assert not role.rolsuper and not role.rolbypassrls
        assert db.scalar(text(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE oid='public.organizations'::regclass"
        ))
        principals = [Principal(
            issuer=wechat_issuer(settings), subject='synthetic-' + str(uuid4()), status='pending',
        ) for _ in range(3)]
        db.add_all(principals)
        db.commit()
        ids = [p.id for p in principals]
        orgs = [personal_space_id(p) for p in principals]

    barrier = Barrier(4)

    def register():
        with SessionLocal() as db:
            # Populate a stale pending identity before the row-lock refresh.
            assert db.get(Principal, ids[0]).status == 'pending'
            barrier.wait(timeout=10)
            organization = ensure_personal_space(db, settings, ids[0])
            db.commit()
            return organization

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: register(), range(4)))
    assert results.count(orgs[0]) == 1 and results.count(None) == 3

    with SessionLocal() as db:
        assert ensure_personal_space(db, settings, ids[1]) == orgs[1]
        db.commit()
        for pid, oid in zip(ids[:2], orgs[:2], strict=True):
            set_tenant_context(db, organization_id=oid, principal_id=pid)
            membership = db.scalars(select(OrganizationMembership)).one()
            assert (membership.organization_id, membership.principal_id, membership.role) == (
                oid, pid, 'examiner',
            )
            assert db.scalar(select(func.count()).select_from(AuditEvent)) == 2
            db.add(Project(organization_id=oid, name='Synthetic private project'))
            db.commit()
        for pid, oid in zip(ids[:2], orgs[:2], strict=True):
            set_tenant_context(db, organization_id=None, principal_id=pid)
            assert [o.id for o in db.scalars(select(Organization))] == [oid]
            assert [m.organization_id for m in db.scalars(select(OrganizationMembership))] == [oid]
            set_tenant_context(db, organization_id=oid, principal_id=pid)
            assert [p.organization_id for p in db.scalars(select(Project))] == [oid]
            assert db.get(Organization, orgs[1] if oid == orgs[0] else orgs[0]) is None
        set_tenant_context(db, organization_id=orgs[0], principal_id=ids[0])
        membership = db.scalars(select(OrganizationMembership)).one()
        membership.status = 'revoked'
        db.commit()
        assert ensure_personal_space(db, settings, ids[0]) is None
        db.commit()
        assert db.get(OrganizationMembership, membership.id).status == 'revoked'
        set_tenant_context(db, organization_id=None, principal_id=ids[0])
        assert db.scalars(select(Organization)).all() == []
        # Rollback must remove both space and membership, and undo activation.
        assert ensure_personal_space(db, settings, ids[2]) == orgs[2]
        db.rollback()
        assert db.get(Principal, ids[2]).status == 'pending'
        set_tenant_context(db, organization_id=orgs[2], principal_id=ids[2])
        assert db.get(Organization, orgs[2]) is None
        assert db.scalar(select(func.count()).select_from(OrganizationMembership)) == 0
    engine.dispose()
    print('PASS: runtime RLS, four concurrent registrations, idempotency, private spaces, revocation, rollback')


if __name__ == '__main__':
    verify()
