from __future__ import annotations

from sqlalchemy.orm import Session

from ..jobs import (
    analyze_visual_document_task,
    generate_golden_dataset_task,
    run_benchmark_task,
)
from ..models import BackgroundJob

TASKS = {
    "golden_dataset": generate_golden_dataset_task,
    "visual_document": analyze_visual_document_task,
    "benchmark": run_benchmark_task,
}


class JobQueueUnavailable(RuntimeError):
    """Raised when a background job cannot be handed to the worker queue."""


def enqueue_job(db: Session, *, kind: str, project_id: str | None, payload: dict) -> BackgroundJob:
    if kind not in TASKS:
        raise ValueError(f"Unsupported job kind: {kind}")
    job = BackgroundJob(project_id=project_id, kind=kind, payload=payload, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        result = TASKS[kind].delay(job.id)
    except Exception as exc:
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
