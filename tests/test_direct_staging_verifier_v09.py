from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest


def _load_verifier_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "verify-v09-direct-staging.py"
    )
    spec = importlib.util.spec_from_file_location(
        "verify_v09_direct_staging",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_direct_staging_client_ignores_environment_proxy_by_default(monkeypatch):
    module = _load_verifier_module()
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    run = module.AcceptanceRun(
        base_url="http://127.0.0.1:8020/",
        organization_id="org",
        identities={},
    )

    assert captured["base_url"] == "http://127.0.0.1:8020"
    assert captured["timeout"] == 180
    assert captured["trust_env"] is False
    run.close()
    assert captured["closed"] is True


def test_direct_staging_client_can_explicitly_use_environment_proxy(monkeypatch):
    module = _load_verifier_module()
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            return None

    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    module.AcceptanceRun(
        base_url="https://staging.example.test",
        organization_id="org",
        identities={},
        trust_env=True,
    )

    assert captured["trust_env"] is True


def test_direct_staging_waits_for_completed_blueprint_job(monkeypatch):
    module = _load_verifier_module()

    class Response:
        status_code = 200
        text = ""

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **_kwargs):
            self.responses = iter(
                [
                    Response({"id": "job-1", "status": "running"}),
                    Response(
                        {
                            "id": "job-1",
                            "status": "completed",
                            "result": {"blueprint": {"id": "blueprint-1"}},
                        }
                    ),
                ]
            )

        def get(self, *_args, **_kwargs):
            return next(self.responses)

        def close(self):
            return None

    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    run = module.AcceptanceRun(
        base_url="http://127.0.0.1:8020",
        organization_id="org",
        identities={"owner": "principal"},
    )

    completed = run.wait_for_job("job-1", poll_seconds=0)

    assert completed["status"] == "completed"
    assert run.results[-1]["name"] == "real_qwen_planner_async_completion"
    assert run.results[-1]["status"] == "passed"


def test_direct_staging_rejects_failed_blueprint_job(monkeypatch):
    module = _load_verifier_module()

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {
                "id": "job-1",
                "status": "failed",
                "error_code": "provider_error",
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        def get(self, *_args, **_kwargs):
            return Response()

        def close(self):
            return None

    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    run = module.AcceptanceRun(
        base_url="http://127.0.0.1:8020",
        organization_id="org",
        identities={"owner": "principal"},
    )

    with pytest.raises(AssertionError, match="unexpected terminal job"):
        run.wait_for_job("job-1", poll_seconds=0)

    assert run.results[-1]["status"] == "failed"


def test_direct_staging_rejects_a_previously_used_candidate_membership():
    module = _load_verifier_module()
    candidate_id = "candidate-principal"
    calls: list[dict] = []

    class FakeRun:
        def check(self, name, method, path, **kwargs):
            calls.append(
                {
                    "name": name,
                    "method": method,
                    "path": path,
                    **kwargs,
                }
            )
            raise AssertionError("membership create must not run")

        @staticmethod
        def assert_condition(name, condition, detail):
            assert name == "candidate_membership_unused"
            if not condition:
                raise AssertionError(detail)

    with pytest.raises(AssertionError, match="fresh isolated database"):
        module.prepare_candidate_membership(
            FakeRun(),
            organization_id="org",
            candidate_principal_id=candidate_id,
            memberships=[
                {
                    "id": "membership-1",
                    "principal_id": candidate_id,
                    "role": "auditor",
                    "status": "revoked",
                    "version": 7,
                }
            ],
        )

    assert calls == []
