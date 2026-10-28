from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException, WebSocket
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import VoiceSession
from .authentication import current_authentication
from .authorization import require_workbench_capability
from .tenancy import current_tenant_context


def _origin(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
        if scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        return scheme, parsed.hostname.lower(), parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None


def validate_voice_origin(websocket: WebSocket, settings: Settings) -> None:
    # Use the configured public callback origin behind a reverse proxy. Never
    # trust an arbitrary X-Forwarded-Host supplied by a client.
    expected = _origin(settings.oidc_redirect_uri or str(websocket.url))
    supplied = websocket.headers.get("origin", "")
    if not expected or _origin(supplied) != expected:
        raise HTTPException(403, "Voice connection origin is not allowed")


def authorized_qwen_voice(
    websocket: WebSocket, db: Session, voice_session_id: str, settings: Settings,
) -> VoiceSession:
    validate_voice_origin(websocket, settings)
    if settings.auth_mode == "disabled" and settings.app_env == "production":
        raise HTTPException(403, "Voice connections require authentication")
    authentication = current_authentication(websocket, db)
    require_workbench_capability("session.conduct")(websocket, authentication, db)
    # The shared dependency binds both principal and organization before RLS
    # evaluates this lookup, including on every later transaction/revalidation.
    voice = db.get(VoiceSession, voice_session_id)
    tenant = current_tenant_context(db)
    if (
        voice is None or voice.provider != "qwen"
        or voice.organization_id != tenant.organization_id
    ):
        raise HTTPException(404, "Voice session not found")
    if voice.status not in {"ready", "connected"}:
        raise HTTPException(409, "Voice session is no longer active")
    return voice


def qwen_connection_error(reason: str) -> dict:
    if "model not exist" in reason.lower() or "model_not_found" in reason.lower():
        return {
            "code": "qwen_model_unavailable",
            "message": "千问拒绝了当前配置的实时模型（Model not exist）。请核对百炼地域、业务空间和模型权限；系统未切换模型。",
        }
    return {
        "code": "qwen_realtime_unavailable",
        "message": "千问实时语音连接失败或已中断，请重试并检查服务端接入配置。",
    }
