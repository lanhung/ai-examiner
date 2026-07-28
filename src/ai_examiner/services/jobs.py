from __future__ import annotations

from sqlalchemy.orm import Session

from ..jobs import (
    analyze_visual_document_task,
    delete_learner_memory_task,
    export_learner_memory_task,
    generate_golden_dataset_task,
    run_benchmark_task,
)
from ..models import BackgroundJob, Project
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
    job = BackgroundJob(
        organization_id=resolved_organization_id,
        actor_principal_id=resolved_actor_id,
        project_id=project_id,
        kind=kind,
        payload=payload,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        result = TASKS[kind].delay(
            job.id,
            job.organization_id,
            job.actor_principal_id,
        )
    except Exception as exc:
        db.expire_all()
        failed_job = db.get(BackgroundJob, job.id)
        if failed_job and failed_job.status == "failed":
            return failed_job
        job.status = "failed"
        job.error = "Background queue unavailable"
        db.commit()
        raise JobQueueUnavailable(
            "Background queue unavailable. Start Redis and the Celery worker, "
            "or set CELERY_ALWAYS_EAGER=true for a single-process test deployment."
        ) from exc
    job.celery_task_id = result.id
    db.commit()
    db.refresh(job)
    return job


def serialize_job(job: BackgroundJob) -> dict:
    return {
        "id": job.id,
        "organization_id": job.organization_id,
        "actor_principal_id": job.actor_principal_id,
        "project_id": job.project_id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result": job.result,
        "error": job.error,
        "celery_task_id": job.celery_task_id,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
