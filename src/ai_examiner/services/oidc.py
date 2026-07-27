from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from jwt import PyJWK
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    BrowserAuthSession,
    OIDCLoginTransaction,
    OrganizationMembership,
    Principal,
    utcnow,
)

MAX_TOKEN_CHARS = 16_384
MAX_DISCOVERY_BYTES = 256_000
MAX_JWKS_BYTES = 1_000_000
MAX_JWKS_KEYS = 100


class OIDCError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        *,
        public_code: str = "token_invalid",
        public_message: str = "Authentication failed.",
    ) -> None:
        super().__init__(public_message)
        self.reason_code = reason_code
        self.public_code = public_code
        self.public_message = public_message


def _dependency_error(reason_code: str) -> OIDCError:
    return OIDCError(
        reason_code,
        public_code="dependency_unavailable",
        public_message="Authentication is temporarily unavailable.",
    )


@dataclass(frozen=True)
class OIDCProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None
    signing_algorithms: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedToken:
    issuer: str
    subject: str
    scopes: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    display_name: str | None
    email: str | None
    nonce: str | None = None


@dataclass(frozen=True)
class AuthenticationContext:
    method: str
    principal_id: str | None
    issuer: str | None
    subject: str | None
    scopes: frozenset[str]
    session_id: str | None = None

    @property
    def authenticated(self) -> bool:
        return self.principal_id is not None


@dataclass(frozen=True)
class LoginStart:
    authorization_url: str
    expires_at: datetime


@dataclass(frozen=True)
class LoginComplete:
    principal_id: str
    session_token: str
    expires_at: datetime


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _safe_https_url(value: str, *, allow_insecure_http: bool) -> bool:
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.fragment:
        return False
    if parsed.scheme == "https" and parsed.netloc:
        return True
    return bool(
        allow_insecure_http
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost"}
    )


class OIDCDiscoveryCache:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._client = client
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._metadata: OIDCProviderMetadata | None = None
        self._metadata_loaded_at = 0.0
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0
        self._unknown_kids: dict[str, float] = {}

    @property
    def discovery_url(self) -> str:
        issuer = (self.settings.oidc_issuer_url or "").rstrip("/")
        return f"{issuer}/.well-known/openid-configuration"

    def _get_json(self, url: str, *, max_bytes: int, reason: str) -> dict[str, Any]:
        if not _safe_https_url(
            url,
            allow_insecure_http=self.settings.oidc_allow_insecure_http,
        ):
            raise _dependency_error(reason)
        try:
            if self._client is not None:
                response = self._client.get(url)
            else:
                response = httpx.get(
                    url,
                    timeout=self.settings.oidc_http_timeout_seconds,
                    follow_redirects=False,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise _dependency_error(reason) from exc
        if response.status_code != 200 or len(response.content) > max_bytes:
            raise _dependency_error(reason)
        try:
            payload = response.json()
        except ValueError as exc:
            raise _dependency_error(reason) from exc
        if not isinstance(payload, dict):
            raise _dependency_error(reason)
        return payload

    def get_metadata(self, *, force: bool = False) -> OIDCProviderMetadata:
        with self._lock:
            now = self._monotonic()
            if (
                not force
                and self._metadata is not None
                and now - self._metadata_loaded_at
                < self.settings.oidc_discovery_ttl_seconds
            ):
                return self._metadata

            payload = self._get_json(
                self.discovery_url,
                max_bytes=MAX_DISCOVERY_BYTES,
                reason="oidc_discovery_unavailable",
            )
            expected_issuer = self.settings.oidc_issuer_url or ""
            if payload.get("issuer") != expected_issuer:
                raise _dependency_error("oidc_discovery_issuer_mismatch")
            required_urls = {
                "authorization_endpoint": payload.get("authorization_endpoint"),
                "token_endpoint": payload.get("token_endpoint"),
                "jwks_uri": payload.get("jwks_uri"),
            }
            if any(
                not isinstance(value, str)
                or not _safe_https_url(
                    value,
                    allow_insecure_http=self.settings.oidc_allow_insecure_http,
                )
                for value in required_urls.values()
            ):
                raise _dependency_error("oidc_discovery_invalid_endpoint")
            advertised = payload.get("id_token_signing_alg_values_supported") or []
            if not isinstance(advertised, list):
                raise _dependency_error("oidc_discovery_invalid_algorithms")
            algorithms = tuple(
                item
                for item in self.settings.oidc_algorithm_allowlist
                if item in advertised
            )
            if not algorithms:
                raise _dependency_error("oidc_discovery_no_allowed_algorithm")

            end_session = payload.get("end_session_endpoint")
            if end_session is not None and (
                not isinstance(end_session, str)
                or not _safe_https_url(
                    end_session,
                    allow_insecure_http=self.settings.oidc_allow_insecure_http,
                )
            ):
                end_session = None
            self._metadata = OIDCProviderMetadata(
                issuer=expected_issuer,
                authorization_endpoint=required_urls["authorization_endpoint"],
                token_endpoint=required_urls["token_endpoint"],
                jwks_uri=required_urls["jwks_uri"],
                end_session_endpoint=end_session,
                signing_algorithms=algorithms,
            )
            self._metadata_loaded_at = now
            return self._metadata

    def get_jwks(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = self._monotonic()
            if (
                not force
                and self._jwks is not None
                and now - self._jwks_loaded_at < self.settings.oidc_jwks_ttl_seconds
            ):
                return self._jwks
            metadata = self.get_metadata()
            payload = self._get_json(
                metadata.jwks_uri,
                max_bytes=MAX_JWKS_BYTES,
                reason="oidc_jwks_unavailable",
            )
            keys = payload.get("keys")
            if (
                not isinstance(keys, list)
                or not keys
                or len(keys) > MAX_JWKS_KEYS
                or any(not isinstance(item, dict) for item in keys)
            ):
                raise _dependency_error("oidc_jwks_invalid")
            self._jwks = {"keys": keys}
            self._jwks_loaded_at = now
            return self._jwks

    def signing_key(self, kid: str, algorithm: str) -> PyJWK:
        with self._lock:
            now = self._monotonic()
            negative_ttl = min(30.0, float(self.settings.oidc_jwks_ttl_seconds))
            last_unknown = self._unknown_kids.get(kid)
            if last_unknown is not None and now - last_unknown < negative_ttl:
                raise OIDCError("oidc_unknown_kid")

            for refresh in (False, True):
                jwks = self.get_jwks(force=refresh)
                matches = [
                    item
                    for item in jwks["keys"]
                    if item.get("kid") == kid
                    and item.get("use", "sig") == "sig"
                    and item.get("alg", algorithm) == algorithm
                ]
                if len(matches) == 1:
                    self._unknown_kids.pop(kid, None)
                    try:
                        return PyJWK.from_dict(matches[0], algorithm=algorithm)
                    except (jwt.PyJWKError, ValueError) as exc:
                        raise _dependency_error("oidc_jwk_invalid") from exc
                if len(matches) > 1:
                    raise _dependency_error("oidc_jwk_ambiguous")

            self._unknown_kids[kid] = now
            if len(self._unknown_kids) > 1000:
                oldest = min(self._unknown_kids, key=self._unknown_kids.__getitem__)
                self._unknown_kids.pop(oldest, None)
            raise OIDCError("oidc_unknown_kid")

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        metadata = self.get_metadata()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.settings.oidc_client_id or "",
            "code_verifier": code_verifier,
        }
        if self.settings.oidc_client_secret is not None:
            form["client_secret"] = (
                self.settings.oidc_client_secret.get_secret_value()
            )
        try:
            if self._client is not None:
                response = self._client.post(metadata.token_endpoint, data=form)
            else:
                response = httpx.post(
                    metadata.token_endpoint,
                    data=form,
                    timeout=self.settings.oidc_http_timeout_seconds,
                    follow_redirects=False,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise _dependency_error("oidc_token_exchange_unavailable") from exc
        if response.status_code != 200 or len(response.content) > MAX_DISCOVERY_BYTES:
            raise OIDCError("oidc_token_exchange_failed")
        try:
            payload = response.json()
        except ValueError as exc:
            raise _dependency_error("oidc_token_exchange_invalid") from exc
        if not isinstance(payload, dict):
            raise _dependency_error("oidc_token_exchange_invalid")
        return payload


class OIDCTokenValidator:
    def __init__(self, settings: Settings, cache: OIDCDiscoveryCache) -> None:
        self.settings = settings
        self.cache = cache

    def _decode(
        self,
        token: str,
        *,
        audience: str,
        allowed_types: frozenset[str],
        require_nonce: bool,
    ) -> dict[str, Any]:
        if not token or len(token) > MAX_TOKEN_CHARS:
            raise OIDCError("token_size_invalid")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise OIDCError("token_header_invalid") from exc
        algorithm = header.get("alg")
        kid = header.get("kid")
        token_type = str(header.get("typ") or "").lower()
        if algorithm not in self.settings.oidc_algorithm_allowlist:
            raise OIDCError("token_algorithm_denied")
        if token_type not in allowed_types:
            raise OIDCError("token_type_denied")
        if not isinstance(kid, str) or not kid or len(kid) > 200:
            raise OIDCError("token_kid_invalid")
        if "jku" in header or "x5u" in header:
            raise OIDCError("token_remote_key_header_denied")

        key = self.cache.signing_key(kid, algorithm)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.settings.oidc_algorithm_allowlist),
                audience=audience,
                issuer=self.settings.oidc_issuer_url,
                leeway=self.settings.oidc_clock_skew_seconds,
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise OIDCError("token_claim_or_signature_invalid") from exc
        if not isinstance(claims, dict):
            raise OIDCError("token_claims_invalid")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 500:
            raise OIDCError("token_subject_invalid")
        if require_nonce and (
            not isinstance(claims.get("nonce"), str) or not claims["nonce"]
        ):
            raise OIDCError("id_token_nonce_missing")
        if require_nonce:
            token_audience = claims.get("aud")
            authorized_party = claims.get("azp")
            if isinstance(token_audience, list) and len(token_audience) > 1:
                if authorized_party != audience:
                    raise OIDCError("id_token_authorized_party_invalid")
            elif authorized_party is not None and authorized_party != audience:
                raise OIDCError("id_token_authorized_party_invalid")
        now = datetime.now(UTC).timestamp()
        issued_at = float(claims["iat"])
        if issued_at > now + self.settings.oidc_clock_skew_seconds:
            raise OIDCError("token_iat_in_future")
        return claims

    def validate_access_token(self, token: str) -> ValidatedToken:
        claims = self._decode(
            token,
            audience=self.settings.oidc_audience or "",
            allowed_types=frozenset(
                self.settings.oidc_access_token_type_allowlist
            ),
            require_nonce=False,
        )
        raw_scope = claims.get("scope", claims.get("scp", ""))
        if isinstance(raw_scope, str):
            scopes = frozenset(raw_scope.split())
        elif isinstance(raw_scope, list) and all(
            isinstance(item, str) for item in raw_scope
        ):
            scopes = frozenset(raw_scope)
        else:
            raise OIDCError("token_scope_invalid")
        if not self.settings.oidc_required_scope_set <= scopes:
            raise OIDCError(
                "token_scope_insufficient",
                public_code="authorization_denied",
                public_message="The requested operation is not permitted.",
            )
        return self._identity(claims, scopes=scopes)

    def validate_id_token(
        self,
        token: str,
        *,
        expected_nonce_hash: str,
        access_token: str,
    ) -> ValidatedToken:
        claims = self._decode(
            token,
            audience=self.settings.oidc_client_id or "",
            allowed_types=frozenset({"jwt"}),
            require_nonce=True,
        )
        if not secrets.compare_digest(
            _sha256(claims["nonce"]),
            expected_nonce_hash,
        ):
            raise OIDCError("id_token_nonce_mismatch")
        token_hash = claims.get("at_hash")
        if token_hash is not None:
            if not isinstance(token_hash, str) or not token_hash:
                raise OIDCError("id_token_access_hash_invalid")
            try:
                algorithm = jwt.get_unverified_header(token)["alg"]
                digest = jwt.get_algorithm_by_name(algorithm).compute_hash_digest(
                    access_token.encode("ascii")
                )
            except (KeyError, UnicodeEncodeError, NotImplementedError) as exc:
                raise OIDCError("id_token_access_hash_invalid") from exc
            expected_hash = _base64url(digest[: len(digest) // 2])
            if not secrets.compare_digest(token_hash, expected_hash):
                raise OIDCError("id_token_access_hash_invalid")
        return self._identity(claims, scopes=frozenset())

    @staticmethod
    def _identity(
        claims: dict[str, Any],
        *,
        scopes: frozenset[str],
    ) -> ValidatedToken:
        name = claims.get("name") or claims.get("preferred_username")
        email = claims.get("email")
        return ValidatedToken(
            issuer=str(claims["iss"]),
            subject=str(claims["sub"]),
            scopes=scopes,
            issued_at=datetime.fromtimestamp(float(claims["iat"]), UTC),
            expires_at=datetime.fromtimestamp(float(claims["exp"]), UTC),
            display_name=str(name)[:200] if isinstance(name, str) and name else None,
            email=str(email)[:320] if isinstance(email, str) and email else None,
            nonce=claims.get("nonce") if isinstance(claims.get("nonce"), str) else None,
        )


class OIDCAuthenticator:
    def __init__(
        self,
        settings: Settings,
        *,
        cache: OIDCDiscoveryCache | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or OIDCDiscoveryCache(settings)
        self.validator = OIDCTokenValidator(settings, self.cache)

    def _fernet(self) -> Fernet:
        if self.settings.auth_session_secret is None:
            raise OIDCError(
                "auth_session_secret_missing",
                public_code="dependency_unavailable",
                public_message="Authentication is unavailable.",
            )
        digest = hashlib.sha256(
            self.settings.auth_session_secret.get_secret_value().encode("utf-8")
        ).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def begin_login(self, db: Session) -> LoginStart:
        metadata = self.cache.get_metadata()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        nonce = secrets.token_urlsafe(32)
        now = utcnow()
        expires_at = now + timedelta(minutes=self.settings.oidc_login_ttl_minutes)
        transaction = OIDCLoginTransaction(
            state_hash=_sha256(state),
            code_verifier_ciphertext=self._fernet().encrypt(
                verifier.encode("utf-8")
            ).decode("ascii"),
            nonce_hash=_sha256(nonce),
            redirect_uri=self.settings.oidc_redirect_uri or "",
            created_at=now,
            expires_at=expires_at,
        )
        db.add(transaction)
        db.commit()
        challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.oidc_client_id or "",
                "redirect_uri": transaction.redirect_uri,
                "scope": " ".join(self.settings.oidc_scope_list),
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return LoginStart(
            authorization_url=f"{metadata.authorization_endpoint}?{query}",
            expires_at=expires_at,
        )

    def complete_login(
        self,
        db: Session,
        *,
        state: str,
        code: str,
    ) -> LoginComplete:
        if not state or len(state) > 500 or not code or len(code) > 4000:
            raise OIDCError("oidc_callback_invalid")
        transaction = db.scalar(
            select(OIDCLoginTransaction).where(
                OIDCLoginTransaction.state_hash == _sha256(state)
            )
        )
        now = utcnow()
        if (
            transaction is None
            or transaction.consumed_at is not None
            or _aware(transaction.expires_at) <= now
        ):
            raise OIDCError("oidc_state_invalid")
        transaction.consumed_at = now
        db.commit()
        try:
            verifier = self._fernet().decrypt(
                transaction.code_verifier_ciphertext.encode("ascii"),
                ttl=self.settings.oidc_login_ttl_minutes * 60,
            ).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise OIDCError("oidc_verifier_invalid") from exc

        token_response = self.cache.exchange_code(
            code=code,
            code_verifier=verifier,
            redirect_uri=transaction.redirect_uri,
        )
        access_token = token_response.get("access_token")
        id_token = token_response.get("id_token")
        if not isinstance(access_token, str) or not isinstance(id_token, str):
            raise OIDCError("oidc_token_response_missing_tokens")
        access_identity = self.validator.validate_access_token(access_token)
        id_identity = self.validator.validate_id_token(
            id_token,
            expected_nonce_hash=transaction.nonce_hash,
            access_token=access_token,
        )
        if (
            access_identity.issuer != id_identity.issuer
            or access_identity.subject != id_identity.subject
        ):
            raise OIDCError("oidc_token_identity_mismatch")
        principal = self.resolve_principal(db, access_identity)
        session_now = utcnow()
        session_secret = secrets.token_urlsafe(48)
        session_expiry = min(
            access_identity.expires_at,
            session_now + timedelta(minutes=self.settings.oidc_session_max_minutes),
        )
        browser_session = BrowserAuthSession(
            principal_id=principal.id,
            session_token_hash=_sha256(session_secret),
            scopes_json=sorted(access_identity.scopes),
            auth_time=access_identity.issued_at,
            expires_at=session_expiry,
            last_seen_at=session_now,
            created_at=session_now,
        )
        db.add(browser_session)
        db.commit()
        return LoginComplete(
            principal_id=principal.id,
            session_token=session_secret,
            expires_at=session_expiry,
        )

    def resolve_principal(self, db: Session, token: ValidatedToken) -> Principal:
        principal = db.scalar(
            select(Principal).where(
                Principal.issuer == token.issuer,
                Principal.subject == token.subject,
            )
        )
        if principal is None:
            policy = self.settings.oidc_principal_provisioning
            if policy == "existing_only":
                raise OIDCError(
                    "principal_not_provisioned",
                    public_code="authorization_denied",
                    public_message="The requested operation is not permitted.",
                )
            principal = Principal(
                issuer=token.issuer,
                subject=token.subject,
                display_name=token.display_name,
                email=token.email,
                status="active" if policy == "auto_active" else "pending",
            )
            db.add(principal)
            db.commit()
            db.refresh(principal)
        if principal.status != "active":
            raise OIDCError(
                "principal_inactive",
                public_code="authorization_denied",
                public_message="The requested operation is not permitted.",
            )
        return principal

    def authenticate_bearer(self, db: Session, token: str) -> AuthenticationContext:
        identity = self.validator.validate_access_token(token)
        principal = self.resolve_principal(db, identity)
        return AuthenticationContext(
            method="oidc_bearer",
            principal_id=principal.id,
            issuer=identity.issuer,
            subject=identity.subject,
            scopes=identity.scopes,
        )

    def authenticate_session(
        self,
        db: Session,
        session_token: str,
    ) -> AuthenticationContext:
        if not session_token or len(session_token) > 500:
            raise OIDCError("browser_session_invalid")
        browser_session = db.scalar(
            select(BrowserAuthSession).where(
                BrowserAuthSession.session_token_hash == _sha256(session_token)
            )
        )
        now = utcnow()
        if (
            browser_session is None
            or browser_session.revoked_at is not None
            or _aware(browser_session.expires_at) <= now
        ):
            raise OIDCError("browser_session_invalid")
        principal = db.get(Principal, browser_session.principal_id)
        if principal is None or principal.status != "active":
            raise OIDCError(
                "principal_inactive",
                public_code="authorization_denied",
                public_message="The requested operation is not permitted.",
            )
        if now - _aware(browser_session.last_seen_at) >= timedelta(minutes=5):
            browser_session.last_seen_at = now
            db.commit()
        return AuthenticationContext(
            method="oidc_session",
            principal_id=principal.id,
            issuer=principal.issuer,
            subject=principal.subject,
            scopes=frozenset(browser_session.scopes_json),
            session_id=browser_session.id,
        )

    def revoke_session(self, db: Session, session_token: str | None) -> bool:
        if not session_token:
            return False
        browser_session = db.scalar(
            select(BrowserAuthSession).where(
                BrowserAuthSession.session_token_hash == _sha256(session_token)
            )
        )
        if browser_session is None or browser_session.revoked_at is not None:
            return False
        browser_session.revoked_at = utcnow()
        db.commit()
        return True

    def me(self, db: Session, context: AuthenticationContext) -> dict[str, Any]:
        if not context.authenticated:
            return {
                "principal": None,
                "organizations": [],
                "authentication": {"method": context.method},
            }
        principal = db.get(Principal, context.principal_id)
        if principal is None:
            raise OIDCError("principal_not_found")
        memberships = db.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.principal_id == principal.id,
                OrganizationMembership.status == "active",
            )
        ).all()
        return {
            "principal": {
                "id": principal.id,
                "display_name": principal.display_name,
                "status": principal.status,
            },
            "organizations": [
                {
                    "id": membership.organization_id,
                    "role": membership.role,
                    "membership_id": membership.id,
                }
                for membership in memberships
            ],
            "authentication": {
                "method": context.method,
                "issuer": context.issuer,
            },
        }
