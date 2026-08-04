from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient


def _issuer_module(monkeypatch):
    monkeypatch.setenv("TEST_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("TEST_OIDC_REDIRECT_URI", "https://examiner.example.test/callback")
    path = Path(__file__).resolve().parents[1] / "deploy/testing/oidc_test_issuer.py"
    spec = importlib.util.spec_from_file_location("oidc_test_issuer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_staging_oidc_issuer_completes_pkce_code_flow(monkeypatch):
    issuer = _issuer_module(monkeypatch)
    verifier = "v" * 64
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    client = TestClient(issuer.app)

    metadata = client.get("/.well-known/openid-configuration")
    assert metadata.status_code == 200
    assert metadata.json()["issuer"] == "https://issuer.example.test"
    assert client.get("/jwks").json()["keys"][0]["kid"]

    authorized = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": issuer.CLIENT_ID,
            "redirect_uri": issuer.REDIRECT_URI,
            "state": "state-value",
            "nonce": "nonce-value",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorized.headers["location"]).query)["code"][0]
    token = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": issuer.REDIRECT_URI,
            "client_id": issuer.CLIENT_ID,
            "code_verifier": verifier,
        },
    )

    assert authorized.status_code == 302
    assert token.status_code == 200
    assert token.json()["access_token"]
    assert token.json()["id_token"]
    assert "secret" not in os.environ.get("TEST_OIDC_ISSUER", "")
