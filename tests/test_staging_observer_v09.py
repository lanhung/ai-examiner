from __future__ import annotations

import httpx

from ai_examiner.staging_observer import sample


def test_staging_sample_requires_ready_oidc_mode():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"version": "0.9.0"})
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "checks": {"authentication": {"ready": True, "mode": "oidc"}},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = sample(client, "https://staging.example")

    assert result["healthy"] is True
    assert result["ready"] is True
    assert result["oidc_ready"] is True
    assert result["version"] == "0.9.0"
