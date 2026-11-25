import httpx
import pytest

from ai_examiner.config import Settings
from ai_examiner.services.oidc import OIDCDiscoveryCache, OIDCError

ISSUER = "https://login.example.test/realm"


def settings(**overrides):
    return Settings(**{
        "auth_mode": "oidc", "oidc_issuer_url": ISSUER,
        "oidc_backchannel_base_url": "http://127.0.0.1:6009",
        "oidc_allow_insecure_http": True, **overrides,
    })


def test_backchannel_preserves_public_metadata_and_uses_internal_transport():
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
            })
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [{"kid": "test-only"}]})
        if request.url.path == "/token":
            assert request.method == "POST"
            return httpx.Response(200, json={"access_token": "test-only"})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cache = OIDCDiscoveryCache(settings(), client=client)
        metadata = cache.get_metadata()
        assert metadata.issuer == ISSUER
        assert metadata.authorization_endpoint == ISSUER + "/authorize"
        assert metadata.token_endpoint == ISSUER + "/token"
        cache.get_jwks()
        cache.exchange_code(code="test-code", code_verifier="test-verifier", redirect_uri="https://app.example.test/callback")
    assert requests == ["http://127.0.0.1:6009" + path for path in (
        "/.well-known/openid-configuration", "/jwks", "/token")]


@pytest.mark.parametrize("value", [
    "http://10.0.0.1:6009", "http://evil.example.test", "https://user:pass@host.test",
    "https://host.test?token=value", "https://host.test#fragment", "file:///tmp/jwks",
    "https://host.test:99999", "https://host.test:0", "https://[broken",
])
def test_backchannel_rejects_unsafe_addresses(value):
    configured = settings(oidc_backchannel_base_url=value)
    assert "oidc_backchannel_invalid_url" in configured.auth_configuration_issues()
    with pytest.raises(OIDCError, match="temporarily unavailable"):
        OIDCDiscoveryCache(configured)._backchannel_url(ISSUER + "/jwks")


def test_loopback_http_requires_explicit_permission():
    configured = settings(oidc_allow_insecure_http=False)
    assert configured.oidc_backchannel_configuration_issues()
    assert not settings(oidc_backchannel_base_url="https://private.example.test").oidc_backchannel_configuration_issues()


def test_backchannel_does_not_rewrite_other_issuers_or_authorization_urls():
    cache = OIDCDiscoveryCache(settings())
    for value in ["https://other.example.test/jwks", "https://login.example.test/realm-evil/jwks"]:
        assert cache._backchannel_url(value) == value
    configured = settings(oidc_backchannel_base_url=None)
    assert OIDCDiscoveryCache(configured)._backchannel_url(ISSUER + "/jwks") == ISSUER + "/jwks"


def test_backchannel_still_rejects_wrong_public_issuer():
    def handler(request):
        return httpx.Response(200, json={"issuer": "http://127.0.0.1:6009"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OIDCError) as exc:
            OIDCDiscoveryCache(settings(), client=client).get_metadata()
    assert exc.value.reason_code == "oidc_discovery_issuer_mismatch"
