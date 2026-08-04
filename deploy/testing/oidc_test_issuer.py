from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import RedirectResponse
from jwt.algorithms import RSAAlgorithm

ISSUER = os.environ["TEST_OIDC_ISSUER"].rstrip("/")
CLIENT_ID = os.getenv("TEST_OIDC_CLIENT_ID", "ai-examiner-web")
AUDIENCE = os.getenv("TEST_OIDC_AUDIENCE", "ai-examiner-api")
REDIRECT_URI = os.environ["TEST_OIDC_REDIRECT_URI"]
SUBJECT = os.getenv("TEST_OIDC_SUBJECT", "release-owner")
KID = "ai-examiner-staging-rsa"

private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
codes: dict[str, dict[str, str]] = {}
codes_lock = threading.Lock()
app = FastAPI(title="AI Examiner staging OIDC issuer", docs_url=None, redoc_url=None)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _token(*, audience: str, token_type: str, nonce: str | None = None, at_hash: str | None = None) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "name": "AI Examiner Release Owner",
        "email": "release-owner@example.test",
    }
    if audience == AUDIENCE:
        claims["scope"] = "openid profile email exam:read"
    if nonce:
        claims["nonce"] = nonce
    if at_hash:
        claims["at_hash"] = at_hash
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": KID, "typ": token_type},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "issuer": ISSUER}


@app.get("/.well-known/openid-configuration")
def discovery() -> dict[str, object]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "end_session_endpoint": f"{ISSUER}/logout",
        "id_token_signing_alg_values_supported": ["RS256"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    }


@app.get("/jwks")
def jwks() -> dict[str, object]:
    return {"keys": [jwk]}


@app.get("/authorize")
def authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(...),
    nonce: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query(...),
) -> RedirectResponse:
    if (
        response_type != "code"
        or client_id != CLIENT_ID
        or redirect_uri != REDIRECT_URI
        or code_challenge_method != "S256"
    ):
        raise HTTPException(status_code=400, detail="invalid_authorization_request")
    code = secrets.token_urlsafe(32)
    with codes_lock:
        codes[code] = {
            "challenge": code_challenge,
            "nonce": nonce,
            "redirect_uri": redirect_uri,
        }
    return RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'state': state})}", status_code=302)


@app.post("/token")
def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    code_verifier: str = Form(...),
) -> dict[str, object]:
    with codes_lock:
        transaction = codes.pop(code, None)
    challenge = _base64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    if (
        grant_type != "authorization_code"
        or client_id != CLIENT_ID
        or redirect_uri != REDIRECT_URI
        or transaction is None
        or not secrets.compare_digest(challenge, transaction["challenge"])
    ):
        raise HTTPException(status_code=400, detail="invalid_grant")
    access_token = _token(audience=AUDIENCE, token_type="at+jwt")
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    id_token = _token(
        audience=CLIENT_ID,
        token_type="JWT",
        nonce=transaction["nonce"],
        at_hash=_base64url(digest[: len(digest) // 2]),
    )
    return {
        "access_token": access_token,
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": 900,
        "scope": "openid profile email exam:read",
    }


@app.get("/logout", response_model=None)
def logout(post_logout_redirect_uri: str | None = None) -> RedirectResponse | dict[str, str]:
    if post_logout_redirect_uri:
        return RedirectResponse(post_logout_redirect_uri, status_code=302)
    return {"status": "logged_out"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("TEST_OIDC_BIND", "127.0.0.1"),
        port=int(os.getenv("TEST_OIDC_PORT", "6008")),
        access_log=False,
    )
