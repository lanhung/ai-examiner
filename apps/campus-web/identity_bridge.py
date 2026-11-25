"""Use existing identity/audit/RLS contracts without changing the old API files."""
import hashlib
import secrets
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from ai_examiner.config import get_settings
from ai_examiner.db import SessionLocal
from ai_examiner.models import BrowserAuthSession, Organization, OrganizationMembership, Principal, utcnow
from ai_examiner.school_api import teacher_scope
from ai_examiner.services.audit import append_audit_event
from ai_examiner.services.membership_admin import MembershipAdministrationService
from ai_examiner.services.oidc import OIDCAuthenticator, OIDCError
from ai_examiner.services.tenancy import set_tenant_context

ISSUER="campus:password:v1"


class IdentityBridge:
    def __init__(self):
        self.settings=get_settings()
        self.cookie_name=self.settings.oidc_session_cookie_name

    def _ids(self,account):
        principal=str(uuid5(NAMESPACE_URL,ISSUER+":"+account["id"]))
        org=str(uuid5(NAMESPACE_URL,ISSUER+":personal:"+principal))
        return principal,org

    def _space(self,db,principal,org):
        set_tenant_context(db,organization_id=org,principal_id=principal.id)
        o=db.get(Organization,org)
        m=db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.principal_id==principal.id,
            OrganizationMembership.organization_id==org))
        if not o or o.status!="active" or o.slug!="campus-personal-"+principal.id or not m or m.status!="active":
            raise HTTPException(403,"个人空间不可用，请联系管理员")
        from ai_examiner.services.authorization import effective_capabilities
        if "blueprint.create" not in effective_capabilities(m.role):
            raise HTTPException(403,"个人空间权限不足")

    def issue(self,account):
        pid,org=self._ids(account)
        with SessionLocal() as db:
            # Concurrent logins for the same new account cannot create two identities.
            if db.get_bind().dialect.name=="postgresql":
                from sqlalchemy import text
                lock=int.from_bytes(hashlib.sha256(pid.encode()).digest()[:8],"big",signed=True)
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":lock})
            p=db.get(Principal,pid)
            set_tenant_context(db,organization_id=org,principal_id=pid)
            if p is None:
                p=Principal(id=pid,issuer=ISSUER,subject=account["id"],display_name=account["nickname"],status="active")
                if db.get(Organization,org):
                    raise HTTPException(409,"账号空间冲突，请联系管理员")
                db.add(p)
                db.add(Organization(id=org,slug="campus-personal-"+pid,display_name="我的个人空间",status="active"))
                db.flush()
                MembershipAdministrationService(db).create(organization_id=org,principal_id=pid,
                                                            role="examiner",status="active",commit=False)
                append_audit_event(db,organization_id=org,actor_type="principal",actor_id=pid,
                    authentication_method="campus_password",action="campus.principal.self_register",
                    resource_type="principal",resource_id=pid,outcome="succeeded",
                    reason_code="personal_registration",request_id=str(uuid4()),trace_id=uuid4().hex,
                    settings=self.settings)
            if p.issuer!=ISSUER or p.subject!=account["id"] or p.status!="active":
                raise HTTPException(403,"账号已停用或身份记录不匹配")
            self._space(db,p,org)
            token=secrets.token_urlsafe(48)
            now=utcnow()
            db.add(BrowserAuthSession(principal_id=pid,session_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                scopes_json=[],auth_time=now,expires_at=now+timedelta(minutes=self.settings.oidc_session_max_minutes),
                last_seen_at=now,created_at=now))
            db.commit()
        return token

    def workspace(self,token,role):
        with SessionLocal() as db:
            try:
                auth=OIDCAuthenticator(self.settings).authenticate_session(db,token)
            except OIDCError:
                raise HTTPException(401,"登录已过期，请重新登录") from None
            p=db.get(Principal,auth.principal_id)
            if not p or p.issuer!=ISSUER:
                raise HTTPException(403,"网页账号身份不匹配")
            if role=="teacher":
                org=teacher_scope(db,p).organization_id
            elif role=="student":
                _,org=self._ids({"id":p.subject})
                self._space(db,p,org)
            else:raise HTTPException(422,"角色无效")
            return org

    def revoke(self,token):
        with SessionLocal() as db:
            OIDCAuthenticator(self.settings).revoke_session(db,token)
