"""Opt-in WeChat identity exchange and server-controlled personal provisioning."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import replace
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import BrowserAuthSession, Organization, OrganizationMembership, Principal, utcnow
from .audit import append_audit_event
from .membership_admin import MembershipAdministrationService
from .oidc import AuthenticationContext, OIDCAuthenticator, OIDCError
from .tenancy import set_tenant_context, tenant_context

TOKEN_PREFIX = "wxmp_"


def check_login_capacity(settings: Settings) -> None:
    """Distributed app-wide admission gate; never key by a login code or secret."""
    from redis import Redis
    from redis.exceptions import RedisError

    require_wechat(settings)
    key = f"ai-examiner:wechat-login:{settings.wechat_app_id}:{int(time.time()) // 60}"
    script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],120) end; return n"
    try:
        with Redis.from_url(
            settings.redis_url, socket_connect_timeout=2, socket_timeout=2
        ) as client:
            count = int(client.eval(script, 1, key))
    except (RedisError, ValueError):
        raise OIDCError(
            "wechat_admission_unavailable",
            public_code="dependency_unavailable",
            public_message="登录保护服务暂不可用，请稍后重试。",
        ) from None
    if count > settings.wechat_login_limit_per_minute:
        raise OIDCError(
            "wechat_rate_limited",
            public_code="rate_limited",
            public_message="登录请求过多，请一分钟后重试。",
        )


def require_wechat(settings: Settings) -> None:
    if (
        not settings.wechat_enabled
        or settings.auth_mode != "oidc"
        or not settings.wechat_app_id
        or not settings.wechat_app_secret
        or not settings.wechat_app_secret.get_secret_value()
    ):
        raise OIDCError(
            "wechat_disabled",
            public_code="dependency_unavailable",
            public_message="微信登录尚未启用，请联系管理员。",
        )


def wechat_issuer(settings: Settings) -> str:
    return f"wechat:miniprogram:{settings.wechat_app_id}"


def personal_space_id(principal: Principal) -> str:
    return str(uuid5(NAMESPACE_URL, f"ai-examiner:wechat-personal:{principal.issuer}:{principal.id}"))


def ensure_personal_space(db: Session, settings: Settings, principal_id: str) -> str | None:
    """Provision once after verified WeChat exchange; caller commits with the login session."""
    require_wechat(settings)
    if settings.wechat_registration_mode != "personal":
        raise ValueError("Personal registration is not enabled")
    # Serialize concurrent first logins in PostgreSQL, refreshing any identity-map copy.
    principal = db.scalar(
        select(Principal).where(Principal.id == principal_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if principal is None or principal.issuer != wechat_issuer(settings):
        raise OIDCError("wechat_principal_wrong_app")
    if principal.status == "active":
        return None
    if principal.status != "pending":
        raise OIDCError(
            "wechat_principal_unavailable", public_code="authorization_denied",
            public_message="账号已停用，请联系管理员。",
        )

    organization_id = personal_space_id(principal)
    with tenant_context(db, organization_id=None, principal_id=principal.id):
        try:
            existing_membership = db.scalar(
                select(OrganizationMembership).where(OrganizationMembership.principal_id == principal.id)
            )
            set_tenant_context(db, organization_id=organization_id, principal_id=principal.id)
            # Never adopt another organization or recreate an intentionally removed membership.
            if existing_membership is not None or db.get(Organization, organization_id) is not None:
                raise OIDCError(
                    "wechat_registration_conflict", public_code="authorization_denied",
                    public_message="账号已有授权记录，请联系管理员核对。",
                )
            organization = Organization(
                id=organization_id, slug=f"wx-personal-{principal.id}",
                display_name="我的个人空间", status="active",
            )
            db.add(organization)
            principal.status = "active"
            principal.updated_at = utcnow()
            db.flush()
            MembershipAdministrationService(db).create(
                organization_id=organization_id, principal_id=principal.id,
                role="examiner", status="active", commit=False,
            )
            request_id, trace_id = str(uuid4()), uuid4().hex
            for action, resource_type, resource_id in (
                ("organization.create", "organization", organization_id),
                ("wechat.principal.self_register", "principal", principal.id),
            ):
                append_audit_event(
                    db, organization_id=organization_id, actor_type="principal",
                    actor_id=principal.id, authentication_method="wechat_code",
                    action=action, resource_type=resource_type, resource_id=resource_id,
                    outcome="succeeded", reason_code="personal_registration",
                    request_id=request_id, trace_id=trace_id,
                    metadata={"role": "examiner"}, settings=settings,
                )
        except Exception:
            # Registration, membership and audit must be atomic even if audit persistence fails.
            db.rollback()
            raise
    return organization_id


def exchange_code(settings: Settings, code: str) -> str:
    require_wechat(settings)
    # Keep this secret-bearing request out of application HTTP tracing. WeChat accepts
    # code2Session through its documented GET query, so use an uninstrumented
    # stdlib HTTPS connection, never log its URL, body, code or session_key.
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    params = urllib.parse.urlencode(
        {
            "appid": settings.wechat_app_id,
            "secret": settings.wechat_app_secret.get_secret_value(),
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(
            "https://api.weixin.qq.com/sns/jscode2session?" + params,
            timeout=10,
        ) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("Oversized response")
            data = json.loads(raw)
    except (OSError, ValueError):
        raise OIDCError(
            "wechat_upstream_unavailable",
            public_code="dependency_unavailable",
            public_message="微信登录服务暂不可用，请稍后重试。",
        ) from None
    if not isinstance(data, dict):
        raise OIDCError("wechat_invalid_response")
    if data.get("errcode", 0) != 0:
        raise OIDCError("wechat_exchange_rejected", public_message="微信登录失败，请重新登录。")
    openid = data.get("openid")
    if not isinstance(openid, str) or not 1 <= len(openid) <= 128:
        raise OIDCError("wechat_invalid_openid")
    return openid


def login(db: Session, settings: Settings, code: str) -> dict:
    openid = exchange_code(settings, code)
    issuer = wechat_issuer(settings)
    query = select(Principal).where(Principal.issuer == issuer, Principal.subject == openid)
    principal = db.scalar(query)
    if principal is None:
        principal = Principal(
            issuer=issuer, subject=openid, status="pending", display_name="微信用户"
        )
        db.add(principal)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            principal = db.scalar(query)
            if principal is None:
                raise
    if settings.wechat_registration_mode == "personal":
        ensure_personal_space(db, settings, principal.id)
    if principal.status in {"suspended", "disabled"}:
        raise OIDCError(
            "wechat_principal_unavailable", public_code="authorization_denied",
            public_message="账号已停用，请联系管理员。",
        )
    if principal.status != "active":
        raise OIDCError(
            "wechat_principal_pending",
            public_code="authorization_denied",
            public_message=f"账号待管理员启用并分配组织。申请编号：{principal.id}",
        )
    now = utcnow()
    token = TOKEN_PREFIX + secrets.token_urlsafe(48)
    expiry = now + timedelta(minutes=settings.oidc_session_max_minutes)
    db.add(
        BrowserAuthSession(
            principal_id=principal.id,
            session_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            scopes_json=[],
            auth_time=now,
            expires_at=expiry,
            last_seen_at=now,
            created_at=now,
        )
    )
    db.commit()
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": expiry,
        "idle_minutes": settings.oidc_session_idle_minutes,
    }


def authenticate(db: Session, settings: Settings, token: str) -> AuthenticationContext:
    require_wechat(settings)
    if not token.startswith(TOKEN_PREFIX):
        raise OIDCError("wechat_token_invalid")
    context = OIDCAuthenticator(settings).authenticate_session(db, token)
    if context.issuer != wechat_issuer(settings):
        raise OIDCError("wechat_token_wrong_app")
    return replace(context, method="wechat_session")
