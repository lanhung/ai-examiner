from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..jobs import (
    analyze_visual_document_task,
    delete_learner_memory_task,
    export_learner_memory_task,
    generate_golden_dataset_task,
    run_benchmark_task,
)
from ..models import BackgroundJob, Project
from .job_control import (
    JOB_CAPABILITIES,
    TaskEnvelope,
    append_job_audit,
    recover_stale_jobs,
    request_job_cancellation,
    reset_job_for_retry,
)
from .tenancy import current_tenant_context, tenant_organization_or_legacy

TASKS = {
    "golden_dataset": generate_golden_dataset_task,
    "visual_document": analyze_visual_document_task,
    "benchmark": run_benchmark_task,
    "memory_export": export_learner_memory_task,
    "memory_deletion": delete_learner_memory_task,
}


class JobQueueUnavailable(RuntimeError):
    """Raised when a background job cannot be handed to the worker queue."""


def enqueue_job(
    db: Session,
    *,
    kind: str,
    project_id: str | None,
    payload: dict,
    organization_id: str | None = None,
    actor_principal_id: str | None = None,
    idempotency_key: str | None = None,
    max_attempts: int | None = None,
) -> BackgroundJob:
    if kind not in TASKS:
        raise ValueError(f"Unsupported job kind: {kind}")
    context = current_tenant_context(db)
    resolved_organization_id = organization_id
    if project_id:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError("Project not found")
        if (
            resolved_organization_id is not None
            and resolved_organization_id != project.organization_id
        ):
            raise ValueError("Job organization does not match project organization")
        resolved_organization_id = project.organization_id
    resolved_organization_id = (
        resolved_organization_id or tenant_organization_or_legacy(db)
    )
    if (
        context.organization_id is not None
        and context.organization_id != resolved_organization_id
    ):
        raise ValueError("Job organization does not match transaction context")
    resolved_actor_id = actor_principal_id or context.principal_id
    resolved_idempotency_key = (idempotency_key or uuid4().hex).strip()
    if not resolved_idempotency_key or len(resolved_idempotency_key) > 160:
        raise ValueError("Job idempotency key must contain 1 to 160 characters")
    existing = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.organization_id == resolved_organization_id,
            BackgroundJob.kind == kind,
            BackgroundJob.idempotency_key == resolved_idempotency_key,
        )
    )
    if existing is not None:
        if existing.actor_principal_id != resolved_actor_id:
            raise ValueError("Job idempotency key belongs to another actor")
        candidate = TaskEnvelope.create(
            job_id=existing.id,
            organization_id=resolved_organization_id,
            actor_principal_id=resolved_actor_id,
            kind=kind,
            required_capability=JOB_CAPABILITIES[kind],
            authorization_mode="membership" if resolved_actor_id else "legacy_local",
            idempotency_key=resolved_idempotency_key,
            payload=payload,
        )
        persisted = ensure_job_envelope(existing)
        if candidate.payload_digest != persisted.payload_digest:
            raise ValueError("Job idempotency key was reused with a different payload")
        return existing
    job_id = str(uuid4())
    authorization_mode = "membership" if resolved_actor_id else "legacy_local"
    envelope = TaskEnvelope.create(
        job_id=job_id,
        organization_id=resolved_organization_id,
        actor_principal_id=resolved_actor_id,
        kind=kind,
        required_capability=JOB_CAPABILITIES[kind],
        authorization_mode=authorization_mode,
        idempotency_key=resolved_idempotency_key,
        payload=payload,
    )
    job = BackgroundJob(
        id=job_id,
        organization_id=resolved_organization_id,
        actor_principal_id=resolved_actor_id,
        project_id=project_id,
        kind=kind,
        idempotency_key=resolved_idempotency_key,
        envelope_version=envelope.version,
        envelope_json=envelope.as_dict(),
        envelope_digest=envelope.digest,
        required_capability=envelope.required_capability,
        authorization_mode=authorization_mode,
        max_attempts=max_attempts or get_settings().job_max_attempts,
        payload=payload,
        status="queued",
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(BackgroundJob).where(
                BackgroundJob.organization_id == resolved_organization_id,
                BackgroundJob.kind == kind,
                BackgroundJob.idempotency_key == resolved_idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.actor_principal_id != resolved_actor_id:
            raise ValueError("Job idempotency key belongs to another actor") from None
        persisted = ensure_job_envelope(existing)
        if persisted.payload_digest != envelope.payload_digest:
            raise ValueError(
                "Job idempotency key was reused with a different payload"
            ) from None
        return existing
    db.refresh(job)
    try:
        result = TASKS[kind].delay(envelope.as_dict())
    except Exception as exc:
        db.expire_all()
        failed_job = db.get(BackgroundJob, job.id)
        if failed_job and failed_job.status == "failed":
            return failed_job
        job.status = "failed"
        job.error = "queue_unavailable"
        job.terminal_reason = "queue_unavailable"
        append_job_audit(
            db,
            job,
            status="failed",
            reason_code="queue_unavailable",
            outcome="failed",
        )
        db.commit()
        raise JobQueueUnavailable(
            "Background queue unavailable. Start Redis and the Celery worker, "
            "or set CELERY_ALWAYS_EAGER=true for a single-process test deployment."
        ) from exc
    job.celery_task_id = result.id
    db.commit()
    db.refresh(job)
    return job


def ensure_job_envelope(job: BackgroundJob) -> TaskEnvelope:
    if job.envelope_json:
        return TaskEnvelope.from_dict(job.envelope_json)
    idempotency_key = job.idempotency_key or job.id
    required_capability = JOB_CAPABILITIES.get(job.kind)
    if required_capability is None:
        raise ValueError(f"Unsupported job kind: {job.kind}")
    authorization_mode = (
        "membership" if job.actor_principal_id else "legacy_local"
    )
    envelope = TaskEnvelope.create(
        job_id=job.id,
        organization_id=job.organization_id,
        actor_principal_id=job.actor_principal_id,
        kind=job.kind,
        required_capability=required_capability,
        authorization_mode=authorization_mode,
        idempotency_key=idempotency_key,
        payload=job.payload,
    )
    job.idempotency_key = idempotency_key
    job.envelope_version = envelope.version
    job.envelope_json = envelope.as_dict()
    job.envelope_digest = envelope.digest
    job.required_capability = required_capability
    job.authorization_mode = authorization_mode
    return envelope


def dispatch_persisted_job(db: Session, job: BackgroundJob) -> BackgroundJob:
    if job.kind not in TASKS:
        raise ValueError(f"Unsupported job kind: {job.kind}")
    envelope = ensure_job_envelope(job)
    db.commit()
    try:
        result = TASKS[job.kind].delay(envelope.as_dict())
    except Exception as exc:
        job.status = "failed"
        job.error = "queue_unavailable"
        job.terminal_reason = "queue_unavailable"
        append_job_audit(
            db,
            job,
            status="failed",
            reason_code="queue_unavailable",
            outcome="failed",
        )
        db.commit()
        raise JobQueueUnavailable("Background queue unavailable") from exc
    job.celery_task_id = result.id
    db.commit()
    db.refresh(job)
    return job


def cancel_persisted_job(
    db: Session,
    job: BackgroundJob,
    *,
    principal_id: str,
    reason: str,
) -> BackgroundJob:
    job = request_job_cancellation(
        db,
        job,
        principal_id=principal_id,
        reason=reason,
    )
    if job.celery_task_id and not get_settings().celery_always_eager:
        from ..jobs import celery_app

        celery_app.control.revoke(job.celery_task_id, terminate=False)
    return job


def retry_persisted_job(
    db: Session,
    job: BackgroundJob,
    *,
    reason: str,
) -> BackgroundJob:
    reset_job_for_retry(db, job, reason=reason)
    return dispatch_persisted_job(db, job)


def recover_and_dispatch_jobs(
    db: Session,
    *,
    organization_id: str,
) -> list[BackgroundJob]:
    recovered = recover_stale_jobs(
        db,
        get_settings(),
        organization_id=organization_id,
    )
    return [
        dispatch_persisted_job(db, job)
        for job in recovered
    ]


def serialize_job(
    job: BackgroundJob,
    *,
    include_internal: bool = True,
) -> dict:
    payload = {
        "id": job.id,
        "organization_id": job.organization_id,
        "actor_principal_id": job.actor_principal_id,
        "project_id": job.project_id,
        "kind": job.kind,
        "idempotency_key": job.idempotency_key,
        "required_capability": job.required_capability,
        "authorization_mode": job.authorization_mode,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result": job.result,
        "error": job.error,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "retry_class": job.retry_class,
        "next_attempt_at": (
            job.next_attempt_at.isoformat() if job.next_attempt_at else None
        ),
        "lease_expires_at": (
            job.lease_expires_at.isoformat() if job.lease_expires_at else None
        ),
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "cancel_requested_at": (
            job.cancel_requested_at.isoformat()
            if job.cancel_requested_at
            else None
        ),
        "dead_lettered_at": (
            job.dead_lettered_at.isoformat() if job.dead_lettered_at else None
        ),
        "terminal_reason": job.terminal_reason,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
    if include_internal:
        payload["lease_owner"] = job.lease_owner
        payload["celery_task_id"] = job.celery_task_id
    return payload
