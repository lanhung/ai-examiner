from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .services.authentication import CurrentAuthentication, authentication_http_error
from .services.oidc import OIDCAuthenticator, OIDCError
from .services.wechat import TOKEN_PREFIX, check_login_capacity, login


class WechatLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")


def wechat_status(response: Response):
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    enabled = settings.wechat_enabled and settings.auth_mode == "oidc"
    configured = bool(
        settings.wechat_app_id
        and settings.wechat_app_secret
        and settings.wechat_app_secret.get_secret_value()
    )
    state = "disabled" if not enabled else "ready" if configured else "missing_credentials"
    return {
        "state": state,
        "login_available": enabled and configured,
        "app_id": settings.wechat_app_id if enabled else None,
        "registration_mode": settings.wechat_registration_mode if enabled else None,
    }


def wechat_login(
    payload: WechatLogin,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
):
    response.headers["Cache-Control"] = "no-store"
    try:
        check_login_capacity(get_settings())
        return login(db, get_settings(), payload.code)
    except OIDCError as exc:
        if exc.public_code == "rate_limited":
            raise HTTPException(
                429, {"message": exc.public_message}, headers={"Retry-After": "60"}
            ) from exc
        raise authentication_http_error(exc) from exc


def wechat_logout(
    request: Request,
    authentication: CurrentAuthentication,
    db: Annotated[Session, Depends(get_db)],
):
    if authentication.method != "wechat_session":
        raise HTTPException(403, "WeChat session required")
    token = request.headers.get("Authorization", "").partition(" ")[2].strip()
    if not token.startswith(TOKEN_PREFIX):
        raise HTTPException(401, "Invalid session")
    OIDCAuthenticator(get_settings()).revoke_session(db, token)
    return {"logged_out": True}


def register_routes(app: FastAPI) -> None:
    # Direct routes remain visible to the existing startup policy inventory.
    app.add_api_route("/api/v1/wechat/status", wechat_status, methods=["GET"], tags=["wechat"])
    app.add_api_route("/api/v1/wechat/login", wechat_login, methods=["POST"], tags=["wechat"])
    app.add_api_route("/api/v1/wechat/logout", wechat_logout, methods=["POST"], tags=["wechat"])
