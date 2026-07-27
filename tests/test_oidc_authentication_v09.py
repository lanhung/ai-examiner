from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import create_engine, inspect, select, text

from ai_examiner import main as main_module
from ai_examiner.config import Settings
from ai_examiner.db import SessionLocal
from ai_examiner.models import BrowserAuthSession, Principal
from ai_examiner.services.authentication import authentication_http_error, current_authentication
from ai_examiner.services.oidc import (
    AuthenticationContext,
    OIDCAuthenticator,
    OIDCDiscoveryCache,
    OIDCError,
    OIDCTokenValidator,
)

ISSUER = "http://localhost:9100"
AUDIENCE = "ai-examiner-api"
CLIENT_ID = "ai-examiner-web"
KID = "test-rsa-key"


@pytest.fixture
def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return private_key, jwk


def oidc_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "auth_mode": "oidc",
        "oidc_issuer_url": ISSUER,
        "oidc_audience": AUDIENCE,
        "oidc_client_id": CLIENT_ID,
        "oidc_redirect_uri": "http://localhost:8000/api/v1/auth/callback",
        "oidc_post_login_redirect": "/",
        "oidc_allowed_algorithms": "RS256",
        "oidc_access_token_types": "at+jwt",
        "oidc_required_scopes": "exam:read",
        "oidc_principal_provisioning": "auto_active",
        "auth_session_secret": "test-only-auth-session-secret",
        "oidc_allow_insecure_http": True,
    }
    values.update(overrides)
    return Settings(**values)


def provider_metadata() -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "end_session_endpoint": f"{ISSUER}/logout",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def signed_token(
    private_key,
    *,
    audience: str = AUDIENCE,
    subject: str | None = "oidc-user-1",
    issuer: str = ISSUER,
    token_type: str = "at+jwt",
    kid: str = KID,
    scope: str = "openid exam:read",
    nonce: str | None = None,
    expires_delta: timedelta = timedelta(minutes=10),
    issued_delta: timedelta = timedelta(seconds=-5),
    not_before_delta: timedelta | None = None,
    extra_headers: dict | None = None,
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": issuer,
        "aud": audience,
        "exp": now + expires_delta,
        "iat": now + issued_delta,
        "scope": scope,
        "name": "OIDC Test User",
    }
    if subject is not None:
        claims["sub"] = subject
    if nonce is not None:
        claims["nonce"] = nonce
    if not_before_delta is not None:
        claims["nbf"] = now + not_before_delta
    claims.update(extra_claims or {})
    headers = {"kid": kid, "typ": token_type}
    headers.update(extra_headers or {})
    return jwt.encode(claims, private_key, algorithm="RS256", headers=headers)


def oidc_client(jwk: dict, *, token_payload: dict | None = None):
    counts = {"discovery": 0, "jwks": 0, "token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            counts["discovery"] += 1
            return httpx.Response(200, json=provider_metadata())
        if request.url.path == "/jwks":
            counts["jwks"] += 1
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path == "/token":
            counts["token"] += 1
            return httpx.Response(200, json=token_payload or {})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), counts


def validator(settings: Settings, jwk: dict):
    client, counts = oidc_client(jwk)
    cache = OIDCDiscoveryCache(settings, client=client)
    return OIDCTokenValidator(settings, cache), counts


def test_valid_access_token_uses_cached_discovery_and_jwks(signing_material):
    private_key, jwk = signing_material
    settings = oidc_settings()
    token_validator, counts = validator(settings, jwk)
    token = signed_token(private_key)

    first = token_validator.validate_access_token(token)
    second = token_validator.validate_access_token(token)

    assert first.subject == "oidc-user-1"
    assert first.scopes == frozenset({"openid", "exam:read"})
    assert second.subject == first.subject
    assert counts == {"discovery": 1, "jwks": 1, "token": 0}


def test_unknown_kid_forces_one_jwks_refresh(signing_material):
    private_key, current_jwk = signing_material
    rotated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rotated_jwk = json.loads(RSAAlgorithm.to_jwk(rotated_key.public_key()))
    rotated_jwk.update({"kid": "rotated-key", "use": "sig", "alg": "RS256"})
    counts = {"discovery": 0, "jwks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            counts["discovery"] += 1
            return httpx.Response(200, json=provider_metadata())
        if request.url.path == "/jwks":
            counts["jwks"] += 1
            keys = [current_jwk] if counts["jwks"] == 1 else [rotated_jwk]
            return httpx.Response(200, json={"keys": keys})
        return httpx.Response(404)

    settings = oidc_settings()
    cache = OIDCDiscoveryCache(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    token = signed_token(rotated_key, kid="rotated-key")

    identity = OIDCTokenValidator(settings, cache).validate_access_token(token)

    assert identity.subject == "oidc-user-1"
    assert counts == {"discovery": 1, "jwks": 2}
    assert private_key is not None


def test_unknown_kid_negative_cache_prevents_refresh_storm(signing_material):
    private_key, jwk = signing_material
    token_validator, counts = validator(oidc_settings(), jwk)
    token = signed_token(private_key, kid="never-published")

    for _attempt in range(3):
        with pytest.raises(OIDCError) as captured:
            token_validator.validate_access_token(token)
        assert captured.value.reason_code == "oidc_unknown_kid"

    assert counts["jwks"] == 2


@pytest.mark.parametrize(
    ("case", "token_factory"),
    [
        (
            "expired",
            lambda key: signed_token(key, expires_delta=timedelta(minutes=-2)),
        ),
        (
            "future_nbf",
            lambda key: signed_token(
                key,
                not_before_delta=timedelta(minutes=5),
            ),
        ),
        (
            "wrong_issuer",
            lambda key: signed_token(key, issuer="http://localhost:9999"),
        ),
        (
            "wrong_audience",
            lambda key: signed_token(key, audience="other-api"),
        ),
        (
            "missing_subject",
            lambda key: signed_token(key, subject=None),
        ),
        (
            "wrong_type",
            lambda key: signed_token(key, token_type="JWT"),
        ),
        (
            "future_iat",
            lambda key: signed_token(key, issued_delta=timedelta(minutes=5)),
        ),
        (
            "insufficient_scope",
            lambda key: signed_token(key, scope="openid"),
        ),
        (
            "remote_jku",
            lambda key: signed_token(
                key,
                extra_headers={"jku": "https://attacker.invalid/jwks"},
            ),
        ),
        (
            "unknown_kid",
            lambda key: signed_token(key, kid="unknown-key"),
        ),
    ],
)
def test_invalid_access_token_matrix_is_rejected_and_redacted(
    signing_material,
    case,
    token_factory,
):
    private_key, jwk = signing_material
    token_validator, _counts = validator(oidc_settings(), jwk)
    token = token_factory(private_key)

    with pytest.raises(OIDCError) as captured:
        token_validator.validate_access_token(token)

    assert captured.value.reason_code
    assert str(captured.value) in {
        "Authentication failed.",
        "The requested operation is not permitted.",
    }
    assert token not in str(captured.value)
    assert "oidc-user-1" not in str(captured.value)
    assert case


def test_disallowed_algorithm_is_rejected_before_key_lookup(signing_material):
    _private_key, jwk = signing_material
    token_validator, counts = validator(oidc_settings(), jwk)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "oidc-user-1",
            "aud": AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
        },
        "not-a-real-provider-key",
        algorithm="HS256",
        headers={"kid": KID, "typ": "at+jwt"},
    )

    with pytest.raises(OIDCError) as captured:
        token_validator.validate_access_token(token)

    assert captured.value.reason_code == "token_algorithm_denied"
    assert counts["jwks"] == 0


def test_code_pkce_login_provisions_principal_and_hashes_browser_session(
    signing_material,
):
    private_key, jwk = signing_material
    token_payload: dict[str, str] = {}
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=provider_metadata())
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path == "/token":
            return httpx.Response(200, json=token_payload)
        return httpx.Response(404)

    settings = oidc_settings()
    cache = OIDCDiscoveryCache(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    authenticator = OIDCAuthenticator(settings, cache=cache)
    with SessionLocal() as db:
        login = authenticator.begin_login(db)
        query = parse_qs(urlparse(login.authorization_url).query)
        assert query["code_challenge_method"] == ["S256"]
        assert len(query["code_challenge"][0]) >= 43
        assert "code_verifier" not in query
        assert "client_secret" not in login.authorization_url

        nonce = query["nonce"][0]
        access_token = signed_token(private_key)
        access_digest = jwt.get_algorithm_by_name("RS256").compute_hash_digest(
            access_token.encode("ascii")
        )
        access_hash = (
            jwt.utils.base64url_encode(
                access_digest[: len(access_digest) // 2]
            ).decode("ascii")
        )
        token_payload.update(
            {
                "access_token": access_token,
                "id_token": signed_token(
                    private_key,
                    audience=CLIENT_ID,
                    token_type="JWT",
                    nonce=nonce,
                    scope="",
                    extra_claims={"at_hash": access_hash},
                ),
            }
        )
        completed = authenticator.complete_login(
            db,
            state=query["state"][0],
            code="one-time-code",
        )

        principal = db.get(Principal, completed.principal_id)
        browser_session = db.scalar(select(BrowserAuthSession))
        assert principal is not None
        assert principal.status == "active"
        assert browser_session is not None
        assert browser_session.session_token_hash != completed.session_token
        assert "one-time-code" not in browser_session.session_token_hash

        context = authenticator.authenticate_session(db, completed.session_token)
        assert context.principal_id == principal.id
        assert context.method == "oidc_session"
        assert authenticator.revoke_session(db, completed.session_token) is True
        with pytest.raises(OIDCError):
            authenticator.authenticate_session(db, completed.session_token)
        with pytest.raises(OIDCError) as replay:
            authenticator.complete_login(
                db,
                state=query["state"][0],
                code="replayed-code",
            )
        assert replay.value.reason_code == "oidc_state_invalid"

    token_request = next(item for item in requests if item.url.path == "/token")
    token_form = parse_qs(token_request.content.decode("ascii"))
    assert token_form["code_verifier"]
    assert token_form["redirect_uri"] == [settings.oidc_redirect_uri]


def test_id_token_rejects_wrong_access_token_hash(signing_material):
    private_key, jwk = signing_material
    settings = oidc_settings()
    token_validator, _counts = validator(settings, jwk)
    nonce = "test-nonce"
    id_token = signed_token(
        private_key,
        audience=CLIENT_ID,
        token_type="JWT",
        nonce=nonce,
        scope="",
        extra_claims={"at_hash": "incorrect"},
    )

    with pytest.raises(OIDCError) as captured:
        token_validator.validate_id_token(
            id_token,
            expected_nonce_hash=hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
            access_token=signed_token(private_key),
        )

    assert captured.value.reason_code == "id_token_access_hash_invalid"


def test_existing_only_policy_rejects_unknown_principal(signing_material):
    private_key, jwk = signing_material
    settings = oidc_settings(oidc_principal_provisioning="existing_only")
    token_validator, _counts = validator(settings, jwk)
    identity = token_validator.validate_access_token(signed_token(private_key))
    authenticator = OIDCAuthenticator(settings)

    with SessionLocal() as db, pytest.raises(OIDCError) as captured:
        authenticator.resolve_principal(db, identity)

    assert captured.value.reason_code == "principal_not_provisioned"
    assert captured.value.public_code == "authorization_denied"


def test_disabled_principal_is_denied_after_valid_token(signing_material):
    private_key, jwk = signing_material
    settings = oidc_settings(oidc_principal_provisioning="existing_only")
    client, _counts = oidc_client(jwk)
    authenticator = OIDCAuthenticator(
        settings,
        cache=OIDCDiscoveryCache(settings, client=client),
    )
    with SessionLocal() as db:
        db.add(
            Principal(
                issuer=ISSUER,
                subject="oidc-user-1",
                display_name="Disabled User",
                status="disabled",
            )
        )
        db.commit()

        with pytest.raises(OIDCError) as captured:
            authenticator.authenticate_bearer(db, signed_token(private_key))

    assert captured.value.reason_code == "principal_inactive"
    assert captured.value.public_code == "authorization_denied"


def test_production_auth_configuration_is_fail_closed():
    disabled = Settings(app_env="production", auth_mode="disabled")
    insecure_oidc = oidc_settings(
        app_env="production",
        oidc_allow_insecure_http=False,
        oidc_post_login_redirect="https://attacker.invalid",
    )

    assert "unsafe_auth_disabled_in_production" in disabled.auth_configuration_issues()
    assert "oidc_issuer_must_use_https" in insecure_oidc.auth_configuration_issues()
    assert "oidc_redirect_uri_must_use_https" in insecure_oidc.auth_configuration_issues()
    assert (
        "oidc_post_login_redirect_must_be_relative"
        in insecure_oidc.auth_configuration_issues()
    )


def test_production_startup_refuses_disabled_authentication(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(app_env="production", auth_mode="disabled"),
    )

    async def start_application() -> None:
        async with main_module.lifespan(main_module.app):
            pass

    with pytest.raises(RuntimeError, match="unsafe_auth_disabled_in_production"):
        asyncio.run(start_application())


def test_disabled_mode_me_and_readiness_are_explicit(client):
    me = client.get("/api/v1/me")
    ready = client.get("/ready")

    assert me.status_code == 200
    assert me.json() == {
        "principal": None,
        "organizations": [],
        "authentication": {"method": "disabled"},
    }
    assert ready.status_code == 200
    assert ready.json()["checks"]["authentication"] == {
        "ready": True,
        "mode": "disabled",
    }


def test_readiness_fails_when_oidc_dependency_is_unavailable(client, monkeypatch):
    class FailingCache:
        def get_metadata(self):
            raise OIDCError("oidc_discovery_unavailable")

        def get_jwks(self):
            raise AssertionError("JWKS must not load after discovery failure")

    class FailingAuthenticator:
        cache = FailingCache()

    monkeypatch.setattr(main_module, "settings", oidc_settings())
    monkeypatch.setattr(
        main_module,
        "get_oidc_authenticator",
        lambda: FailingAuthenticator(),
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["authentication"] == {
        "ready": False,
        "mode": "oidc",
        "codes": ["oidc_discovery_unavailable"],
    }


def test_oidc_dependency_failure_maps_to_generic_503():
    error = authentication_http_error(
        OIDCError(
            "oidc_jwks_unavailable",
            public_code="dependency_unavailable",
            public_message="Authentication is temporarily unavailable.",
        )
    )

    assert error.status_code == 503
    assert error.detail == {
        "code": "dependency_unavailable",
        "message": "Authentication is temporarily unavailable.",
    }


def test_oidc_context_ignores_untrusted_principal_header(client, monkeypatch):
    with SessionLocal() as db:
        authenticated = Principal(
            issuer=ISSUER,
            subject="authenticated-user",
            display_name="Authenticated User",
            status="active",
        )
        attacker = Principal(
            issuer=ISSUER,
            subject="header-attacker",
            display_name="Header Attacker",
            status="active",
        )
        db.add_all([authenticated, attacker])
        db.commit()
        authenticated_id = authenticated.id
        attacker_id = attacker.id

    monkeypatch.setattr(main_module, "settings", oidc_settings())
    main_module.app.dependency_overrides[current_authentication] = lambda: (
        AuthenticationContext(
            method="oidc_bearer",
            principal_id=authenticated_id,
            issuer=ISSUER,
            subject="authenticated-user",
            scopes=frozenset({"exam:read"}),
        )
    )
    try:
        response = client.get(
            "/api/v1/context",
            headers={"X-AI-Examiner-Principal": attacker_id},
        )
    finally:
        main_module.app.dependency_overrides.pop(current_authentication, None)

    assert response.status_code == 200
    assert response.json()["principal_id"] == authenticated_id
    assert response.json()["principal_id"] != attacker_id


def test_oidc_migration_upgrade_and_downgrade_preserve_principals(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "oidc-migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "AUTH_MODE": "disabled",
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "migration-test-secret",
    }

    def alembic(*arguments: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    alembic("upgrade", "20260727_0008")
    migration_engine = create_engine(database_url)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO principals "
                "(id, issuer, subject, display_name, status, created_at, updated_at) "
                "VALUES "
                "('principal-before-oidc', :issuer, 'migration-user', "
                "'Migration User', 'active', :created_at, :updated_at)"
            ),
            {
                "issuer": ISSUER,
                "created_at": "2026-07-27 00:00:00",
                "updated_at": "2026-07-27 00:00:00",
            },
        )

    alembic("upgrade", "head")
    inspector = inspect(migration_engine)
    assert {
        "oidc_login_transactions",
        "browser_auth_sessions",
    } <= set(inspector.get_table_names())

    alembic("downgrade", "20260727_0008")
    inspector = inspect(migration_engine)
    assert "oidc_login_transactions" not in inspector.get_table_names()
    assert "browser_auth_sessions" not in inspector.get_table_names()
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM principals "
                "WHERE id = 'principal-before-oidc'"
            )
        ) == 1
    migration_engine.dispose()
