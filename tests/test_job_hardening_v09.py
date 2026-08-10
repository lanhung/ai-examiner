from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text

from ai_examiner.config import Settings, get_settings
from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID
from ai_examiner.jobs import TASK_HANDLERS, execute_job_delivery
from ai_examiner.models import (
    BackgroundJob,
    Organization,
    OrganizationMembership,
    Principal,
    Project,
)
from ai_examiner.providers.base import ModelOutputValidationError
from ai_examiner.services import jobs as job_service
from ai_examiner.services.job_control import (
    JobAuthorizationError,
    JobEnvelopeError,
    TaskEnvelope,
    claim_job,
    classify_job_exception,
    fail_job,
    recover_orphaned_queued_jobs,
    recover_stale_jobs,
    request_job_cancellation,
)
from ai_examiner.services.jobs import dispatch_persisted_job, enqueue_job
from ai_examiner.services.tenancy import set_tenant_context


class StubTask:
    calls: list[dict] = []

    @classmethod
    def delay(cls, envelope):
        cls.calls.append(envelope)
        return SimpleNamespace(id=f"delivery-{len(cls.calls)}")


class Delivery:
    def __init__(self, delivery_id: str):
        self.request = SimpleNamespace(id=delivery_id)

    def retry(self, **_kwargs):
        raise AssertionError("Retry was not expected")


def test_job_heartbeat_configuration_fails_closed():
    settings = Settings(
        job_lease_seconds=30,
        job_heartbeat_seconds=30,
    )
    assert settings.job_configuration_issues() == [
        "job_heartbeat_must_be_shorter_than_lease"
    ]


def test_model_output_contract_failures_are_retryable_without_retrying_bad_inputs():
    assert (
        classify_job_exception(ModelOutputValidationError("Planner produced no questions"))
        == "transient"
    )
    assert classify_job_exception(ValueError("Project or document not found")) == "permanent"


def _tenant(
    *,
    slug: str,
    role: str = "owner",
) -> tuple[Organization, Principal, OrganizationMembership, Project]:
    with SessionLocal() as db:
        organization = Organization(
            slug=slug,
            display_name=slug,
            status="active",
            version=1,
        )
        principal = Principal(
            issuer="https://issuer.example",
            subject=f"{slug}-actor",
            status="active",
        )
        db.add_all([organization, principal])
        db.flush()
        membership = OrganizationMembership(
            organization_id=organization.id,
            principal_id=principal.id,
            role=role,
            status="active",
            version=1,
        )
        project = Project(
            organization_id=organization.id,
            name=f"{slug} project",
            domain="test",
            language="en",
        )
        db.add_all([membership, project])
        db.commit()
        return organization, principal, membership, project


def _queued_job(
    monkeypatch,
    *,
    slug: str,
    kind: str = "golden_dataset",
    role: str = "owner",
    idempotency_key: str = "job-key",
    max_attempts: int = 3,
) -> tuple[BackgroundJob, Organization, Principal, OrganizationMembership]:
    StubTask.calls = []
    monkeypatch.setitem(job_service.TASKS, kind, StubTask)
    organization, principal, membership, project = _tenant(slug=slug, role=role)
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        job = enqueue_job(
            db,
            kind=kind,
            project_id=project.id,
            payload={"project_id": project.id, "marker": slug},
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
        )
        return job, organization, principal, membership


def test_task_envelope_is_strict_and_tamper_evident(monkeypatch):
    job, _organization, _principal, _membership = _queued_job(
        monkeypatch,
        slug="envelope",
    )
    envelope = TaskEnvelope.from_dict(job.envelope_json)
    assert envelope.digest == job.envelope_digest
    tampered = {**job.envelope_json, "organization_id": "foreign"}
    with SessionLocal() as db:
        with pytest.raises(JobEnvelopeError):
            claim_job(
                db,
                get_settings(),
                TaskEnvelope.from_dict(tampered),
                delivery_id="tampered-delivery",
            )


def test_enqueue_idempotency_returns_one_job_and_one_delivery(monkeypatch):
    StubTask.calls = []
    monkeypatch.setitem(job_service.TASKS, "golden_dataset", StubTask)
    organization, principal, _membership, project = _tenant(slug="idempotency")
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        first = enqueue_job(
            db,
            kind="golden_dataset",
            project_id=project.id,
            payload={"project_id": project.id},
            idempotency_key="same-request",
        )
        second = enqueue_job(
            db,
            kind="golden_dataset",
            project_id=project.id,
            payload={"project_id": project.id},
            idempotency_key="same-request",
        )
        assert first.id == second.id
        assert db.query(BackgroundJob).count() == 1
        with pytest.raises(ValueError, match="different payload"):
            enqueue_job(
                db,
                kind="golden_dataset",
                project_id=project.id,
                payload={"project_id": project.id, "changed": True},
                idempotency_key="same-request",
            )
    assert len(StubTask.calls) == 1


def test_duplicate_delivery_executes_billable_handler_once(monkeypatch):
    job, _organization, _principal, _membership = _queued_job(
        monkeypatch,
        slug="duplicate",
    )
    calls = []

    def handler(_envelope, _lease_token, _heartbeat):
        calls.append("called")
        return {"result_id": "one"}, "Done"

    monkeypatch.setitem(TASK_HANDLERS, "golden_dataset", handler)
    first = execute_job_delivery(Delivery("delivery-a"), job.envelope_json)
    second = execute_job_delivery(Delivery("delivery-b"), job.envelope_json)
    assert first == {"result_id": "one"}
    assert second["duplicate_delivery"] is True
    assert second["result"] == {"result_id": "one"}
    assert calls == ["called"]


def test_eager_dispatch_preserves_worker_failure_instead_of_masking_queue(
    monkeypatch,
):
    class EagerFailureTask:
        @staticmethod
        def delay(envelope):
            with SessionLocal() as task_db:
                persisted = task_db.get(BackgroundJob, envelope["job_id"])
                persisted.status = "failed"
                persisted.error = "provider_rejected"
                persisted.terminal_reason = "permanent_failure"
                task_db.commit()
            raise RuntimeError("eager task propagated its worker failure")

    StubTask.calls = []
    monkeypatch.setitem(job_service.TASKS, "golden_dataset", StubTask)
    organization, principal, _membership, project = _tenant(slug="eager-failure")
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        job = enqueue_job(
            db,
            kind="golden_dataset",
            project_id=project.id,
            payload={"project_id": project.id},
            idempotency_key="eager-failure",
            dispatch=False,
        )
        monkeypatch.setitem(
            job_service.TASKS,
            "golden_dataset",
            EagerFailureTask,
        )
        result = dispatch_persisted_job(db, job)

        assert result.status == "failed"
        assert result.error == "provider_rejected"
        assert result.terminal_reason == "permanent_failure"


def test_worker_rechecks_current_capability_before_resource_access(monkeypatch):
    job, _organization, _principal, membership = _queued_job(
        monkeypatch,
        slug="revoked",
        role="examiner",
    )
    calls = []
    monkeypatch.setitem(
        TASK_HANDLERS,
        "golden_dataset",
        lambda *_args: calls.append("called"),
    )
    with SessionLocal() as db:
        persisted = db.get(OrganizationMembership, membership.id)
        persisted.role = "learner"
        db.commit()
    with pytest.raises(JobAuthorizationError):
        execute_job_delivery(Delivery("delivery-revoked"), job.envelope_json)
    with SessionLocal() as db:
        persisted_job = db.get(BackgroundJob, job.id)
        assert persisted_job.status == "failed"
        assert persisted_job.terminal_reason == "authorization_revoked"
    assert calls == []


def test_transient_failure_retries_then_dead_letters(monkeypatch):
    job, organization, principal, _membership = _queued_job(
        monkeypatch,
        slug="dead-letter",
        max_attempts=2,
    )
    envelope = TaskEnvelope.from_dict(job.envelope_json)
    settings = get_settings()
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        first = claim_job(db, settings, envelope, delivery_id="attempt-one")
        disposition = fail_job(
            db,
            settings,
            envelope,
            str(first.lease_token),
            TimeoutError("provider timeout"),
        )
        assert disposition.retry is True
        persisted = db.get(BackgroundJob, job.id)
        persisted.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        second = claim_job(db, settings, envelope, delivery_id="attempt-two")
        disposition = fail_job(
            db,
            settings,
            envelope,
            str(second.lease_token),
            TimeoutError("provider timeout"),
        )
        assert disposition.retry is False
        assert disposition.status == "dead_letter"
        assert db.get(BackgroundJob, job.id).dead_lettered_at is not None


def test_cancellation_and_stale_worker_recovery(monkeypatch):
    job, organization, principal, _membership = _queued_job(
        monkeypatch,
        slug="recovery",
    )
    envelope = TaskEnvelope.from_dict(job.envelope_json)
    settings = get_settings()
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        claim = claim_job(db, settings, envelope, delivery_id="lost-worker")
        persisted = db.get(BackgroundJob, job.id)
        persisted.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        recovered = recover_stale_jobs(
            db,
            settings,
            organization_id=organization.id,
        )
        assert [item.id for item in recovered] == [job.id]
        assert recovered[0].status == "retry_scheduled"
        assert recovered[0].lease_token is None

        recovered[0].status = "queued"
        recovered[0].next_attempt_at = None
        db.commit()
        request_job_cancellation(
            db,
            recovered[0],
            principal_id=principal.id,
            reason="Operator cancelled",
        )
        assert db.get(BackgroundJob, job.id).status == "cancelled"
        assert claim.execute is True


def test_orphaned_queued_job_recovery_is_bounded_and_dispatch_safe(monkeypatch):
    job, organization, principal, _membership = _queued_job(
        monkeypatch,
        slug="orphaned-dispatch",
    )
    settings = Settings(
        job_orphan_grace_seconds=60,
        job_recovery_batch_size=1,
    )
    with SessionLocal() as db:
        set_tenant_context(
            db,
            organization_id=organization.id,
            principal_id=principal.id,
        )
        persisted = db.get(BackgroundJob, job.id)
        persisted.celery_task_id = None
        persisted.created_at = datetime.now(UTC) - timedelta(minutes=2)

        recent = BackgroundJob(
            organization_id=organization.id,
            project_id=job.project_id,
            actor_principal_id=principal.id,
            kind=job.kind,
            status="queued",
            created_at=datetime.now(UTC),
        )
        delivered = BackgroundJob(
            organization_id=organization.id,
            project_id=job.project_id,
            actor_principal_id=principal.id,
            kind=job.kind,
            status="queued",
            celery_task_id="already-delivered",
            created_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        db.add_all([recent, delivered])
        db.commit()

        recovered = recover_orphaned_queued_jobs(
            db,
            settings,
            organization_id=organization.id,
        )
        assert [item.id for item in recovered] == [job.id]
        assert "broker dispatch" in recovered[0].message
        assert recent.id not in {item.id for item in recovered}
        assert delivered.id not in {item.id for item in recovered}


def test_job_api_is_tenant_scoped_and_manages_lifecycle(client, monkeypatch):
    job, organization, principal, _membership = _queued_job(
        monkeypatch,
        slug="job-api",
    )
    foreign, foreign_principal, _foreign_membership, _project = _tenant(
        slug="job-api-foreign",
    )
    headers = {
        "X-AI-Examiner-Organization": organization.id,
        "X-AI-Examiner-Principal": principal.id,
    }
    response = client.get(f"/api/v1/jobs/{job.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == job.id
    assert "celery_task_id" not in response.json()
    assert "lease_owner" not in response.json()

    foreign_response = client.get(
        f"/api/v1/jobs/{job.id}",
        headers={
            "X-AI-Examiner-Organization": foreign.id,
            "X-AI-Examiner-Principal": foreign_principal.id,
        },
    )
    assert foreign_response.status_code == 404

    cancelled = client.post(
        f"/api/v1/jobs/{job.id}/cancel",
        headers=headers,
        json={"reason": "No longer needed"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = client.post(
        f"/api/v1/jobs/{job.id}/retry",
        headers=headers,
        json={"reason": "Operator approved retry"},
    )
    assert retried.status_code == 202
    assert retried.json()["status"] == "queued"
    assert len(StubTask.calls) == 2


def test_job_schema_migration_backfills_and_downgrades(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "job-schema.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "job-migration-test-secret",
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

    alembic("upgrade", "20260728_0012")
    migration_engine = create_engine(database_url)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO background_jobs "
                "(id, organization_id, kind, status, progress, message, "
                "payload, result, error, envelope_version, envelope_json, "
                "envelope_digest, required_capability, authorization_mode, "
                "attempt_count, max_attempts, retry_class, terminal_reason, "
                "created_at, updated_at) VALUES "
                "('legacy-job', :organization_id, 'benchmark', 'queued', "
                "0, '', '{}', '{}', '', 1, '{}', '', '', 'legacy_local', "
                "0, 3, '', '', '2026-07-28 00:00:00', "
                "'2026-07-28 00:00:00')"
            ),
            {"organization_id": LEGACY_ORGANIZATION_ID},
        )
    alembic("upgrade", "head")
    inspector = inspect(migration_engine)
    columns = {
        item["name"] for item in inspector.get_columns("background_jobs")
    }
    assert {"idempotency_key", "lease_token", "cancel_requested_at"} <= columns
    with migration_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, idempotency_key, required_capability, "
                "terminal_reason FROM background_jobs WHERE id = 'legacy-job'"
            )
        ).one()
        assert row.status == "failed"
        assert row.idempotency_key == "legacy-job"
        assert row.required_capability == "benchmark.run"
        assert row.terminal_reason == "upgrade_requires_manual_retry"
    alembic("downgrade", "20260728_0012")
    assert "lease_token" not in {
        item["name"] for item in inspect(migration_engine).get_columns("background_jobs")
    }
    migration_engine.dispose()
