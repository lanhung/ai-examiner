import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text

from ai_examiner.config import Settings
from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID
from ai_examiner.models import (
    AuditEvent,
    ModelUsageLedger,
    OrganizationModelPolicy,
    Project,
)
from ai_examiner.providers.base import ProviderResult
from ai_examiner.services import model_governance
from ai_examiner.services.enterprise_identity import bootstrap_owner
from ai_examiner.services.model_governance import (
    GovernedModelProvider,
    MemoryModelRateLimiter,
    ModelGovernanceError,
    ModelGovernanceService,
    ensure_model_policy,
    policy_snapshot,
    update_model_policy,
)


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "model_provider": "mock",
        "model_rate_limit_backend": "memory",
        "model_rate_limit_required": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _provider(
    *,
    profile: str = "mock:heuristic-v2",
    classification: str = "internal",
    limiter=None,
    settings: Settings | None = None,
) -> GovernedModelProvider:
    return GovernedModelProvider(
        settings=settings or _settings(),
        organization_id=LEGACY_ORGANIZATION_ID,
        principal_id="test-principal",
        project_id=None,
        session_id=None,
        classification=classification,
        requested_profile=profile,
        rate_limiter=limiter or MemoryModelRateLimiter(),
    )


def _replace_policy(**values) -> OrganizationModelPolicy:
    with SessionLocal() as db:
        policy = ensure_model_policy(
            db,
            LEGACY_ORGANIZATION_ID,
            principal_id="test-principal",
        )
        update_model_policy(
            db,
            policy,
            values=values,
            principal_id="test-principal",
        )
        db.commit()
        return policy


def test_default_policy_is_versioned_and_digest_bound():
    with SessionLocal() as db:
        policy = ensure_model_policy(db, LEGACY_ORGANIZATION_ID)
        db.commit()
        snapshot = policy_snapshot(policy)

    assert snapshot["version"] == 1
    assert len(snapshot["policy_digest"]) == 64
    assert snapshot["policy_digest"] == (
        model_governance._effective_policy_digest(policy)
    )
    assert snapshot["quota_mode"] == "hard"
    assert any(
        rule["provider"] == "mock"
        for rule in snapshot["allowed_profiles"]
    )


def test_production_requires_governance_and_redis_admission():
    disabled = _settings(
        app_env="production",
        model_governance_enabled=False,
    )
    memory = _settings(
        app_env="production",
        model_rate_limit_backend="memory",
    )
    safe = _settings(
        app_env="production",
        model_rate_limit_backend="redis",
    )

    assert disabled.model_governance_configuration_issues() == [
        "model_governance_required_in_production"
    ]
    assert memory.model_governance_configuration_issues() == [
        "model_governance_requires_redis_in_production"
    ]
    assert safe.model_governance_configuration_issues() == []


def test_readiness_reports_model_admission(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["model_governance"] == {
        "ready": True,
        "enabled": True,
        "rate_limit_backend": "redis",
    }


def test_disallowed_profile_never_constructs_provider(monkeypatch):
    _replace_policy(
        allowed_profiles_json=[
            {
                "provider": "mock",
                "model_pattern": "heuristic-v2",
                "tasks": ["*"],
            }
        ]
    )
    calls = []

    def forbidden_builder(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("provider must not be constructed")

    monkeypatch.setattr(model_governance, "build_provider", forbidden_builder)

    with pytest.raises(ModelGovernanceError) as exc:
        _provider(profile="openai:gpt-5.4-mini").complete_text(
            agent="planner",
            instructions="Ask one grounded question.",
            payload={"document_text": "Evidence"},
        )

    assert exc.value.code == "model_policy_denied"
    assert calls == []
    with SessionLocal() as db:
        ledger = db.scalar(select(ModelUsageLedger))
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "model.call")
        )
        assert ledger.status == "denied"
        assert ledger.actual_provider is None
        assert audit.outcome == "denied"


def test_restricted_data_cannot_use_external_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(
        model_governance,
        "build_provider",
        lambda *_args, **_kwargs: calls.append("called"),
    )

    with pytest.raises(ModelGovernanceError) as exc:
        _provider(
            profile="openai:gpt-5.4-mini",
            classification="restricted",
        ).complete_text(
            agent="planner",
            instructions="Analyze.",
            payload={"document_text": "Restricted evidence"},
        )

    assert exc.value.code == "model_policy_denied"
    assert calls == []


def test_completed_call_records_actual_model_and_policy_snapshot():
    result = _provider().complete_text(
        agent="interviewer",
        instructions="Ask a concise question.",
        payload={"question": "Why?"},
    )

    assert result.provider == "mock"
    with SessionLocal() as db:
        ledger = db.scalar(select(ModelUsageLedger))
        assert ledger.status == "completed"
        assert ledger.actual_provider == "mock"
        assert ledger.actual_model == "heuristic-v2"
        assert ledger.policy_version == 1
        assert len(ledger.policy_snapshot_digest) == 64
        assert ledger.input_tokens == result.input_tokens


def test_hard_quota_denies_before_provider_construction(monkeypatch):
    _replace_policy(
        monthly_budget_usd=0.0000005,
        per_session_budget_usd=0.0,
        per_request_budget_usd=0.0,
        quota_mode="hard",
    )
    calls = []
    monkeypatch.setattr(
        model_governance,
        "build_provider",
        lambda *_args, **_kwargs: calls.append("called"),
    )

    with pytest.raises(ModelGovernanceError) as exc:
        _provider().complete_text(
            agent="planner",
            instructions="Analyze.",
            payload={"document_text": "Evidence"},
        )

    assert exc.value.code == "monthly_quota_exceeded"
    assert calls == []
    with SessionLocal() as db:
        ledger = db.scalar(select(ModelUsageLedger))
        assert ledger.status == "denied"
        assert ledger.reservation_cost_usd >= 0.000001


def test_soft_quota_allows_call_and_marks_ledger():
    _replace_policy(
        monthly_budget_usd=0.0000005,
        per_session_budget_usd=0.0,
        per_request_budget_usd=0.0,
        quota_mode="soft",
    )

    _provider().complete_text(
        agent="planner",
        instructions="Analyze.",
        payload={"document_text": "Evidence"},
    )

    with SessionLocal() as db:
        ledger = db.scalar(select(ModelUsageLedger))
        assert ledger.status == "completed"
        assert ledger.soft_limit_exceeded is True
        assert ledger.denial_reason == "monthly_quota_exceeded"


def test_ordered_fallback_is_rechecked_and_failed_cost_is_accounted(
    monkeypatch,
):
    _replace_policy(
        allowed_profiles_json=[
            {
                "provider": "qwen",
                "model_pattern": "qwen-plus",
                "tasks": ["planner"],
            },
            {
                "provider": "mock",
                "model_pattern": "heuristic-v2",
                "tasks": ["planner"],
            },
        ],
        fallback_profiles_json=["mock:heuristic-v2"],
        fallback_mode="ordered",
    )

    class StubProvider:
        image_model = "stub"

        def __init__(self, profile):
            self.profile = profile

        def complete_text(self, **_kwargs):
            if self.profile.startswith("qwen:"):
                raise TimeoutError("provider timeout")
            return ProviderResult(
                data="fallback result",
                provider="mock",
                model="heuristic-v2",
                input_tokens=3,
                output_tokens=2,
            )

    monkeypatch.setattr(
        model_governance,
        "build_provider",
        lambda _settings, profile: StubProvider(profile),
    )
    result = _provider(profile="qwen:qwen-plus").complete_text(
        agent="planner",
        instructions="Analyze.",
        payload={"document_text": "Evidence"},
    )

    assert result.data == "fallback result"
    with SessionLocal() as db:
        rows = db.scalars(
            select(ModelUsageLedger).order_by(ModelUsageLedger.created_at)
        ).all()
        assert [row.status for row in rows] == ["failed", "completed"]
        assert rows[0].estimated_cost_usd >= rows[0].reservation_cost_usd
        assert rows[1].fallback_from_profile == "qwen:qwen-plus"
        assert rows[1].actual_provider == "mock"


def test_concurrent_call_limit_is_atomic_and_releases_capacity():
    limiter = MemoryModelRateLimiter()
    kwargs = {
        "organization_id": LEGACY_ORGANIZATION_ID,
        "principal_id": "principal",
        "token_units": 1,
        "organization_limit": 100,
        "principal_limit": 100,
        "token_limit": 1000,
        "concurrent_limit": 1,
        "window_seconds": 60,
        "lease_seconds": 60,
    }
    first = limiter.acquire(reservation_id="first", **kwargs)

    def attempt_second():
        with pytest.raises(ModelGovernanceError) as exc:
            limiter.acquire(reservation_id="second", **kwargs)
        return exc.value.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(attempt_second).result() == (
            "organization_concurrency_limited"
        )

    limiter.release(first)
    second = limiter.acquire(reservation_id="second", **kwargs)
    assert second.reservation_id == "second"


def test_concurrent_hard_quota_allows_only_one_reservation():
    _replace_policy(
        monthly_budget_usd=0.0000015,
        per_session_budget_usd=0.0,
        per_request_budget_usd=0.0,
        quota_mode="hard",
        max_concurrent_calls=10,
    )
    service = ModelGovernanceService(
        _settings(),
        rate_limiter=MemoryModelRateLimiter(),
    )
    common = {
        "organization_id": LEGACY_ORGANIZATION_ID,
        "principal_id": "principal",
        "project_id": None,
        "session_id": None,
        "requested_profile": "mock:heuristic-v2",
        "candidate_profile": "mock:heuristic-v2",
        "fallback_from_profile": None,
        "task_type": "planner",
        "classification": "internal",
        "token_units": 1,
    }

    def reserve(index):
        try:
            return service.reserve(request_id=f"concurrent-{index}", **common)
        except ModelGovernanceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, range(2)))

    reservations = [
        outcome for outcome in outcomes if not isinstance(outcome, str)
    ]
    denials = [outcome for outcome in outcomes if isinstance(outcome, str)]
    assert len(reservations) == 1
    assert denials == ["monthly_quota_exceeded"]
    service.fail(reservations[0])


def test_rate_limiter_fail_open_keeps_usage_ledger_consistent():
    class BrokenLimiter:
        def acquire(self, **_kwargs):
            raise ConnectionError("redis unavailable")

        def release(self, _lease):
            return None

    provider = _provider(
        limiter=BrokenLimiter(),
        settings=_settings(model_rate_limit_required=False),
    )
    provider.complete_text(
        agent="planner",
        instructions="Analyze.",
        payload={"document_text": "Evidence"},
    )

    with SessionLocal() as db:
        ledger = db.scalar(select(ModelUsageLedger))
        denied_audit = db.scalar(
            select(AuditEvent).where(AuditEvent.outcome == "denied")
        )
        assert ledger.status == "completed"
        assert ledger.denial_reason == ""
        assert denied_audit is None


def test_model_policy_quota_usage_and_redacted_export_api(client):
    with SessionLocal() as db:
        _organization, owner, _membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject="governance-owner",
        )
        db.commit()
        headers = {
            "X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID,
            "X-AI-Examiner-Principal": owner.id,
        }
    policy_response = client.get(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/model-policy",
        headers=headers,
    )
    assert policy_response.status_code == 200
    initial_version = policy_response.json()["version"]

    policy_update = client.put(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/model-policy",
        headers=headers,
        json={
            "allowed_profiles": [
                {
                    "provider": "mock",
                    "model_pattern": "heuristic-v2",
                    "tasks": ["planner", "interviewer"],
                }
            ],
            "fallback_profiles": [],
            "external_provider_max_classification": "internal",
            "fallback_mode": "deny",
            "provider_retention_allowed": False,
        },
    )
    assert policy_update.status_code == 200
    assert policy_update.json()["version"] == initial_version + 1

    quota_update = client.put(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/quota",
        headers=headers,
        json={
            "quota_mode": "hard",
            "monthly_budget_usd": 25,
            "per_session_budget_usd": 2,
            "per_request_budget_usd": 0.5,
            "soft_limit_ratio": 0.75,
            "organization_requests_per_minute": 60,
            "principal_requests_per_minute": 20,
            "organization_tokens_per_minute": 100000,
            "max_concurrent_calls": 2,
        },
    )
    assert quota_update.status_code == 200
    assert quota_update.json()["monthly_budget_usd"] == 25

    _provider().complete_text(
        agent="planner",
        instructions="Analyze.",
        payload={
            "document_text": "PRIVATE PROMPT MUST NOT APPEAR IN EXPORT",
        },
    )
    usage = client.get(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/usage",
        headers=headers,
    )
    assert usage.status_code == 200
    assert usage.json()["completed_calls"] == 1
    assert usage.json()["by_task"]["planner"]["calls"] == 1
    assert usage.json()["by_project"]["unassigned"]["calls"] == 1

    export = client.get(
        f"/api/v1/organizations/{LEGACY_ORGANIZATION_ID}/usage/export",
        headers=headers,
    )
    assert export.status_code == 200
    assert export.headers["content-type"].startswith(
        "application/x-ndjson"
    )
    assert "PRIVATE PROMPT" not in export.text
    assert '"policy_snapshot_digest"' in export.text


def test_project_data_classification_is_persisted(client):
    with SessionLocal() as db:
        _organization, owner, _membership = bootstrap_owner(
            db,
            issuer="https://issuer.example.test",
            subject="project-owner",
        )
        db.commit()
    response = client.post(
        "/api/projects",
        headers={"X-AI-Examiner-Principal": owner.id},
        json={
            "name": "Restricted research",
            "domain": "research_defense",
            "language": "zh-CN",
            "data_classification": "restricted",
        },
    )
    assert response.status_code == 201
    with SessionLocal() as db:
        project = db.get(Project, response.json()["id"])
        assert project.data_classification == "restricted"


def test_usage_ledger_is_immutable_through_orm():
    _provider().complete_text(
        agent="planner",
        instructions="Analyze.",
        payload={"document_text": "Evidence"},
    )
    with SessionLocal() as db:
        ledger = db.scalar(select(ModelUsageLedger))
        db.delete(ledger)
        with pytest.raises(ValueError, match="cannot be deleted"):
            db.flush()


def test_rate_limiter_denial_changes_reservation_to_denied():
    limiter = MemoryModelRateLimiter()
    service = ModelGovernanceService(
        _settings(),
        rate_limiter=limiter,
    )
    common = {
        "organization_id": LEGACY_ORGANIZATION_ID,
        "principal_id": "principal",
        "project_id": None,
        "session_id": None,
        "requested_profile": "mock:heuristic-v2",
        "candidate_profile": "mock:heuristic-v2",
        "fallback_from_profile": None,
        "task_type": "planner",
        "classification": "internal",
        "token_units": 1,
    }
    _replace_policy(max_concurrent_calls=1)
    first = service.reserve(request_id="first", **common)

    with pytest.raises(ModelGovernanceError) as exc:
        service.reserve(request_id="second", **common)
    assert exc.value.code == "organization_concurrency_limited"

    service.fail(first)
    with SessionLocal() as db:
        rows = db.scalars(
            select(ModelUsageLedger).order_by(ModelUsageLedger.request_id)
        ).all()
        assert {row.status for row in rows} == {"failed", "denied"}
        denied = next(row for row in rows if row.status == "denied")
        assert denied.rate_limit_scope == "organization_concurrency"


def test_model_governance_migration_refuses_usage_evidence_loss(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "model-governance.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "governance-migration-secret",
    }

    def alembic(*arguments: str, expected: int = 0):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return result

    alembic("upgrade", "head")
    migration_engine = create_engine(database_url)
    inspector = inspect(migration_engine)
    assert {
        "organization_model_policies",
        "model_usage_ledger",
    } <= set(inspector.get_table_names())
    assert "data_classification" in {
        column["name"] for column in inspector.get_columns("projects")
    }

    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organization_model_policies "
                "(id, organization_id, version, allowed_profiles_json, "
                "fallback_profiles_json, external_provider_max_classification, "
                "fallback_mode, provider_retention_allowed, quota_mode, "
                "monthly_budget_usd, per_session_budget_usd, "
                "per_request_budget_usd, soft_limit_ratio, "
                "organization_requests_per_minute, "
                "principal_requests_per_minute, "
                "organization_tokens_per_minute, max_concurrent_calls, "
                "policy_digest, created_at, updated_at) VALUES "
                "('policy-proof', :organization_id, 1, '[]', '[]', "
                "'confidential', 'deny', 0, 'hard', 1, 1, 1, 0.8, "
                "10, 10, 1000, 1, :digest, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "organization_id": LEGACY_ORGANIZATION_ID,
                "digest": "1" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO model_usage_ledger "
                "(id, policy_id, policy_version, policy_snapshot_digest, "
                "request_id, task_type, data_classification, "
                "requested_profile, status, reservation_cost_usd, "
                "estimated_cost_usd, input_tokens, output_tokens, "
                "latency_ms, retry_count, rate_limit_scope, denial_reason, "
                "soft_limit_exceeded, created_at, organization_id) VALUES "
                "('usage-proof', 'policy-proof', 1, :digest, "
                "'request-proof', 'planner', 'internal', "
                "'mock:heuristic-v2', 'completed', 0, 0, 0, 0, 0, 0, "
                "'', '', 0, CURRENT_TIMESTAMP, :organization_id)"
            ),
            {
                "organization_id": LEGACY_ORGANIZATION_ID,
                "digest": "1" * 64,
            },
        )

    failed = alembic(
        "downgrade",
        "20260728_0014",
        expected=1,
    )
    assert "refuses to destroy usage evidence" in (
        failed.stdout + failed.stderr
    )
    assert "model_usage_ledger" in inspect(migration_engine).get_table_names()
    migration_engine.dispose()
