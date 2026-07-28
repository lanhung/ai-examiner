from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    BackgroundJob,
    Organization,
    OrganizationMembership,
    Principal,
)
from .audit import append_audit_event
from .authorization import effective_capabilities

ENVELOPE_VERSION = 1
TERMINAL_JOB_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "dead_letter"}
)
RETRYABLE_JOB_STATUSES = frozenset({"queued", "retry_scheduled"})

JOB_CAPABILITIES: dict[str, str] = {
    "golden_dataset": "dataset.manage",
    "visual_document": "document.read",
    "benchmark": "benchmark.run",
    "memory_export": "learner_memory.admin",
    "memory_deletion": "learner_memory.admin",
    "organization_export": "retention.read",
    "data_subject_deletion": "retention.manage",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def append_job_audit(
    db: Session,
    job: BackgroundJob,
    *,
    status: str,
    reason_code: str,
    outcome: str,
) -> None:
    append_audit_event(
        db,
        organization_id=job.organization_id,
        actor_type="worker",
        actor_id=job.actor_principal_id,
        authentication_method=job.authorization_mode,
        action=f"job.{status}",
        resource_type="background_job",
        resource_id=job.id,
        outcome=outcome,
        reason_code=reason_code,
        request_id=f"job:{job.id}",
        trace_id=(job.envelope_digest or job.id.replace("-", ""))[:64],
        metadata={
            "audit_class": "administrative",
            "job_kind": job.kind,
            "terminal_status": status,
        },
        retention_class=(
            "security" if outcome in {"denied", "failed"} else "administrative"
        ),
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class JobControlError(RuntimeError):
    code = "job_control_error"


class JobEnvelopeError(JobControlError):
    code = "job_envelope_invalid"


class JobAuthorizationError(JobControlError):
    code = "job_authorization_denied"


class JobLeaseLost(JobControlError):
    code = "job_lease_lost"


class JobCancelled(JobControlError):
    code = "job_cancelled"


@dataclass(frozen=True)
class TaskEnvelope:
    job_id: str
    organization_id: str
    actor_principal_id: str | None
    kind: str
    required_capability: str
    authorization_mode: str
    idempotency_key: str
    payload_digest: str
    version: int = ENVELOPE_VERSION

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        organization_id: str,
        actor_principal_id: str | None,
        kind: str,
        required_capability: str,
        authorization_mode: str,
        idempotency_key: str,
        payload: dict,
    ) -> TaskEnvelope:
        return cls(
            job_id=job_id,
            organization_id=organization_id,
            actor_principal_id=actor_principal_id,
            kind=kind,
            required_capability=required_capability,
            authorization_mode=authorization_mode,
            idempotency_key=idempotency_key,
            payload_digest=_digest(payload),
        )

    @classmethod
    def from_dict(cls, value: dict) -> TaskEnvelope:
        expected = {
            "version",
            "job_id",
            "organization_id",
            "actor_principal_id",
            "kind",
            "required_capability",
            "authorization_mode",
            "idempotency_key",
            "payload_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise JobEnvelopeError("Task envelope fields are invalid")
        try:
            envelope = cls(
                version=int(value["version"]),
                job_id=str(value["job_id"]),
                organization_id=str(value["organization_id"]),
                actor_principal_id=(
                    str(value["actor_principal_id"])
                    if value["actor_principal_id"] is not None
                    else None
                ),
                kind=str(value["kind"]),
                required_capability=str(value["required_capability"]),
                authorization_mode=str(value["authorization_mode"]),
                idempotency_key=str(value["idempotency_key"]),
                payload_digest=str(value["payload_digest"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise JobEnvelopeError("Task envelope values are invalid") from exc
        if envelope.version != ENVELOPE_VERSION:
            raise JobEnvelopeError("Task envelope version is unsupported")
        if envelope.authorization_mode not in {"membership", "legacy_local"}:
            raise JobEnvelopeError("Task envelope authorization mode is invalid")
        if envelope.kind not in JOB_CAPABILITIES:
            raise JobEnvelopeError("Task envelope job kind is invalid")
        if envelope.required_capability != JOB_CAPABILITIES[envelope.kind]:
            raise JobEnvelopeError("Task envelope capability is invalid")
        return envelope

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "job_id": self.job_id,
            "organization_id": self.organization_id,
            "actor_principal_id": self.actor_principal_id,
            "kind": self.kind,
            "required_capability": self.required_capability,
            "authorization_mode": self.authorization_mode,
            "idempotency_key": self.idempotency_key,
            "payload_digest": self.payload_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())


def verify_job_envelope(job: BackgroundJob, envelope: TaskEnvelope) -> None:
    expected = {
        "id": envelope.job_id,
        "organization_id": envelope.organization_id,
        "actor_principal_id": envelope.actor_principal_id,
        "kind": envelope.kind,
        "required_capability": envelope.required_capability,
        "authorization_mode": envelope.authorization_mode,
        "idempotency_key": envelope.idempotency_key,
        "envelope_version": envelope.version,
        "envelope_digest": envelope.digest,
        "payload_digest": envelope.payload_digest,
    }
    actual = {
        "id": job.id,
        "organization_id": job.organization_id,
        "actor_principal_id": job.actor_principal_id,
        "kind": job.kind,
        "required_capability": job.required_capability,
        "authorization_mode": job.authorization_mode,
        "idempotency_key": job.idempotency_key,
        "envelope_version": job.envelope_version,
        "envelope_digest": job.envelope_digest,
        "payload_digest": _digest(job.payload),
    }
    if actual != expected or job.envelope_json != envelope.as_dict():
        raise JobEnvelopeError("Task envelope does not match persisted job")


def authorize_job_execution(
    db: Session,
    settings: Settings,
    job: BackgroundJob,
) -> None:
    if job.authorization_mode == "legacy_local":
        if settings.auth_mode != "disabled" or settings.app_env == "production":
            raise JobAuthorizationError("Legacy local jobs are not permitted")
        return
    if not job.actor_principal_id:
        raise JobAuthorizationError("Job actor is missing")
    organization = db.get(Organization, job.organization_id)
    principal = db.get(Principal, job.actor_principal_id)
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == job.organization_id,
            OrganizationMembership.principal_id == job.actor_principal_id,
        )
    )
    if (
        organization is None
        or organization.status != "active"
        or principal is None
        or principal.status != "active"
        or membership is None
        or membership.status != "active"
        or job.required_capability not in effective_capabilities(membership.role)
    ):
        raise JobAuthorizationError("Job execution is no longer authorized")


@dataclass(frozen=True)
class JobClaim:
    execute: bool
    lease_token: str | None
    status: str
    result: dict


def claim_job(
    db: Session,
    settings: Settings,
    envelope: TaskEnvelope,
    *,
    delivery_id: str,
) -> JobClaim:
    job = db.get(BackgroundJob, envelope.job_id)
    if job is None or job.organization_id != envelope.organization_id:
        raise JobEnvelopeError("Background job is unavailable")
    verify_job_envelope(job, envelope)
    if job.status in TERMINAL_JOB_STATUSES:
        return JobClaim(False, None, job.status, job.result)
    now = utcnow()
    if job.cancel_requested_at is not None or job.status == "cancelling":
        job.status = "cancelled"
        job.progress = 1.0
        job.message = "Job cancelled"
        job.terminal_reason = "cancel_requested"
        job.completed_at = now
        job.updated_at = now
        append_job_audit(
            db,
            job,
            status="cancelled",
            reason_code="cancel_requested",
            outcome="succeeded",
        )
        db.commit()
        return JobClaim(False, None, "cancelled", {})
    if job.attempt_count >= job.max_attempts:
        job.status = "dead_letter"
        job.dead_lettered_at = now
        job.completed_at = now
        job.terminal_reason = "attempt_limit_exhausted"
        job.updated_at = now
        append_job_audit(
            db,
            job,
            status="dead_letter",
            reason_code="attempt_limit_exhausted",
            outcome="failed",
        )
        db.commit()
        return JobClaim(False, None, "dead_letter", {})
    authorize_job_execution(db, settings, job)
    lease_token = uuid4().hex
    lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
    eligibility = [
        BackgroundJob.id == job.id,
        BackgroundJob.organization_id == job.organization_id,
        BackgroundJob.envelope_digest == envelope.digest,
        BackgroundJob.attempt_count < BackgroundJob.max_attempts,
        or_(
            BackgroundJob.status.in_(RETRYABLE_JOB_STATUSES),
            (
                (BackgroundJob.status == "running")
                & (BackgroundJob.lease_expires_at <= now)
            ),
        ),
        or_(
            BackgroundJob.next_attempt_at.is_(None),
            BackgroundJob.next_attempt_at <= now,
        ),
        BackgroundJob.cancel_requested_at.is_(None),
    ]
    claimed = db.execute(
        update(BackgroundJob)
        .where(*eligibility)
        .values(
            status="running",
            progress=max(job.progress, 0.01),
            message="Worker claimed job",
            attempt_count=BackgroundJob.attempt_count + 1,
            lease_owner=delivery_id[:160],
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
            heartbeat_at=now,
            started_at=job.started_at or now,
            next_attempt_at=None,
            retry_class="",
            error="",
            updated_at=now,
        )
    )
    db.commit()
    if claimed.rowcount != 1:
        db.expire_all()
        current = db.get(BackgroundJob, job.id)
        return JobClaim(
            False,
            None,
            current.status if current else "unavailable",
            current.result if current else {},
        )
    return JobClaim(True, lease_token, "running", {})


def heartbeat_job(
    db: Session,
    settings: Settings,
    envelope: TaskEnvelope,
    lease_token: str,
) -> bool:
    now = utcnow()
    updated = db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == envelope.job_id,
            BackgroundJob.organization_id == envelope.organization_id,
            BackgroundJob.status == "running",
            BackgroundJob.lease_token == lease_token,
            BackgroundJob.cancel_requested_at.is_(None),
        )
        .values(
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=settings.job_lease_seconds),
            updated_at=now,
        )
    )
    db.commit()
    return updated.rowcount == 1


def job_cancel_requested(
    db: Session,
    envelope: TaskEnvelope,
    lease_token: str,
) -> bool:
    job = db.get(BackgroundJob, envelope.job_id)
    if (
        job is None
        or job.organization_id != envelope.organization_id
        or job.lease_token != lease_token
    ):
        raise JobLeaseLost("Job lease is no longer owned by this delivery")
    return job.cancel_requested_at is not None or job.status == "cancelling"


class JobHeartbeat:
    def __init__(
        self,
        *,
        settings: Settings,
        envelope: TaskEnvelope,
        lease_token: str,
        tenant_session_factory,
    ) -> None:
        self.settings = settings
        self.envelope = envelope
        self.lease_token = lease_token
        self.tenant_session_factory = tenant_session_factory
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> JobHeartbeat:
        if not self.settings.celery_always_eager:
            self._thread = threading.Thread(
                target=self._run,
                name=f"job-heartbeat-{self.envelope.job_id}",
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.settings.job_heartbeat_seconds + 1)

    def _run(self) -> None:
        while not self._stop.wait(self.settings.job_heartbeat_seconds):
            try:
                with self.tenant_session_factory(
                    self.envelope.organization_id,
                    self.envelope.actor_principal_id,
                ) as db:
                    if not heartbeat_job(
                        db,
                        self.settings,
                        self.envelope,
                        self.lease_token,
                    ):
                        self._lost.set()
                        return
            except Exception:
                self._lost.set()
                return

    def checkpoint(self) -> None:
        if self._lost.is_set():
            raise JobLeaseLost("Job heartbeat could not renew its lease")
        with self.tenant_session_factory(
            self.envelope.organization_id,
            self.envelope.actor_principal_id,
        ) as db:
            if job_cancel_requested(db, self.envelope, self.lease_token):
                raise JobCancelled("Job cancellation was requested")


def update_running_job(
    db: Session,
    envelope: TaskEnvelope,
    ownership_token: str,
    *,
    commit: bool = True,
    **values: Any,
) -> None:
    values["updated_at"] = utcnow()
    updated = db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == envelope.job_id,
            BackgroundJob.organization_id == envelope.organization_id,
            BackgroundJob.status == "running",
            BackgroundJob.lease_token == ownership_token,
        )
        .values(**values)
    )
    if updated.rowcount != 1:
        db.rollback()
        raise JobLeaseLost("Job lease is no longer owned by this delivery")
    if commit:
        db.commit()


def complete_job(
    db: Session,
    envelope: TaskEnvelope,
    lease_token: str,
    *,
    result: dict,
    message: str,
) -> None:
    now = utcnow()
    update_running_job(
        db,
        envelope,
        lease_token,
        commit=False,
        status="completed",
        progress=1.0,
        message=message,
        result=result,
        error="",
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        heartbeat_at=now,
        completed_at=now,
        terminal_reason="completed",
    )
    job = db.get(BackgroundJob, envelope.job_id)
    if job is None:
        db.rollback()
        raise JobLeaseLost("Completed job could not be reloaded")
    append_job_audit(
        db,
        job,
        status="completed",
        reason_code="completed",
        outcome="succeeded",
    )
    db.commit()


@dataclass(frozen=True)
class JobFailureDisposition:
    status: str
    retry: bool
    countdown: int
    error_code: str


def classify_job_exception(exc: Exception) -> str:
    if isinstance(exc, JobCancelled):
        return "cancelled"
    if isinstance(exc, (JobEnvelopeError, JobAuthorizationError, KeyError, ValueError)):
        return "permanent"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "transient"
    message = str(exc).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "temporarily unavailable",
        "rate limit",
        "too many requests",
        "connection reset",
        "service unavailable",
        "429",
        "502",
        "503",
        "504",
    )
    return "transient" if any(marker in message for marker in transient_markers) else "permanent"


def fail_job(
    db: Session,
    settings: Settings,
    envelope: TaskEnvelope,
    lease_token: str,
    exc: Exception,
) -> JobFailureDisposition:
    job = db.get(BackgroundJob, envelope.job_id)
    if (
        job is None
        or job.organization_id != envelope.organization_id
        or job.lease_token != lease_token
    ):
        raise JobLeaseLost("Job lease is no longer owned by this delivery")
    now = utcnow()
    retry_class = classify_job_exception(exc)
    error_code = getattr(exc, "code", type(exc).__name__)[:120]
    common = {
        "progress": 1.0,
        "error": error_code,
        "retry_class": retry_class,
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at": None,
        "updated_at": now,
    }
    if retry_class == "cancelled" or job.cancel_requested_at is not None:
        job.status = "cancelled"
        job.message = "Job cancelled"
        job.completed_at = now
        job.terminal_reason = "cancel_requested"
        for key, value in common.items():
            setattr(job, key, value)
        append_job_audit(
            db,
            job,
            status="cancelled",
            reason_code="cancel_requested",
            outcome="succeeded",
        )
        db.commit()
        return JobFailureDisposition("cancelled", False, 0, error_code)
    if retry_class == "transient" and job.attempt_count < job.max_attempts:
        countdown = min(
            settings.job_retry_base_seconds * (2 ** max(0, job.attempt_count - 1)),
            3600,
        )
        job.status = "retry_scheduled"
        job.progress = min(job.progress, 0.95)
        job.message = "Transient failure; retry scheduled"
        job.next_attempt_at = now + timedelta(seconds=countdown)
        job.terminal_reason = ""
        for key, value in common.items():
            if key != "progress":
                setattr(job, key, value)
        db.commit()
        return JobFailureDisposition(
            "retry_scheduled",
            True,
            countdown,
            error_code,
        )
    job.status = "dead_letter" if retry_class == "transient" else "failed"
    job.message = (
        "Job moved to dead letter"
        if job.status == "dead_letter"
        else "Job failed permanently"
    )
    job.completed_at = now
    job.dead_lettered_at = now if job.status == "dead_letter" else None
    job.terminal_reason = (
        "attempt_limit_exhausted"
        if job.status == "dead_letter"
        else "permanent_failure"
    )
    for key, value in common.items():
        setattr(job, key, value)
    append_job_audit(
        db,
        job,
        status=job.status,
        reason_code=job.terminal_reason,
        outcome="failed",
    )
    db.commit()
    return JobFailureDisposition(job.status, False, 0, error_code)


def request_job_cancellation(
    db: Session,
    job: BackgroundJob,
    *,
    principal_id: str,
    reason: str,
) -> BackgroundJob:
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    now = utcnow()
    job.cancel_requested_at = now
    job.cancel_requested_by = principal_id
    job.message = reason[:120]
    job.status = "cancelling" if job.status == "running" else "cancelled"
    job.updated_at = now
    if job.status == "cancelled":
        job.progress = 1.0
        job.completed_at = now
        job.terminal_reason = "cancel_requested"
        append_job_audit(
            db,
            job,
            status="cancelled",
            reason_code="cancel_requested",
            outcome="succeeded",
        )
    db.commit()
    db.refresh(job)
    return job


def reset_job_for_retry(
    db: Session,
    job: BackgroundJob,
    *,
    reason: str,
) -> BackgroundJob:
    if job.status not in {"failed", "dead_letter", "cancelled"}:
        raise ValueError("Only terminal unsuccessful jobs can be retried")
    now = utcnow()
    job.status = "queued"
    job.progress = 0.0
    job.message = reason[:120]
    job.error = ""
    job.retry_class = ""
    job.next_attempt_at = None
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.cancel_requested_at = None
    job.cancel_requested_by = None
    job.dead_lettered_at = None
    job.terminal_reason = ""
    job.completed_at = None
    job.attempt_count = 0
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return job


def recover_stale_jobs(
    db: Session,
    settings: Settings,
    *,
    organization_id: str,
) -> list[BackgroundJob]:
    now = utcnow()
    stale = db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.organization_id == organization_id,
            BackgroundJob.status == "running",
            BackgroundJob.lease_expires_at.is_not(None),
            BackgroundJob.lease_expires_at <= now,
        )
        .order_by(BackgroundJob.created_at)
        .limit(settings.job_recovery_batch_size)
    ).all()
    for job in stale:
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.retry_class = "worker_lost"
        job.error = "worker_lease_expired"
        job.updated_at = now
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.completed_at = now
            job.terminal_reason = "cancel_requested"
            append_job_audit(
                db,
                job,
                status="cancelled",
                reason_code="cancel_requested",
                outcome="succeeded",
            )
        elif job.attempt_count >= job.max_attempts:
            job.status = "dead_letter"
            job.dead_lettered_at = now
            job.completed_at = now
            job.terminal_reason = "attempt_limit_exhausted"
            append_job_audit(
                db,
                job,
                status="dead_letter",
                reason_code="attempt_limit_exhausted",
                outcome="failed",
            )
        else:
            job.status = "retry_scheduled"
            job.next_attempt_at = now
            job.message = "Recovered after worker lease expired"
    db.commit()
    return [
        job
        for job in stale
        if job.status == "retry_scheduled"
    ]
