from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import uuid4

from celery import Celery
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal
from .models import (
    BackgroundJob,
    Document,
    GoldenDataset,
    LearnerIdentity,
    MemoryDeletionAudit,
    Project,
)
from .services.benchmark import BenchmarkService
from .services.golden import GoldenDatasetService
from .services.job_control import (
    JobAuthorizationError,
    JobCancelled,
    JobEnvelopeError,
    JobHeartbeat,
    TaskEnvelope,
    append_job_audit,
    claim_job,
    complete_job,
    fail_job,
    update_running_job,
)
from .services.memory_control import MemoryControlService
from .services.tenancy import set_tenant_context
from .services.visual import VisualEvidenceService

settings = get_settings()
celery_app = Celery("ai_examiner", broker=settings.broker_url, backend=settings.result_backend)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_always_eager=settings.celery_always_eager,
    task_eager_propagates=True,
    task_acks_late=True,
    task_acks_on_failure_or_timeout=False,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)

TaskResult = tuple[dict, str]
TaskHandler = Callable[[TaskEnvelope, str, JobHeartbeat], TaskResult]


def _tenant_session(
    organization_id: str,
    actor_principal_id: str | None,
) -> AbstractContextManager[Session]:
    db = SessionLocal()
    set_tenant_context(
        db,
        organization_id=organization_id,
        principal_id=actor_principal_id,
    )
    return db


def _job_or_error(
    db: Session,
    envelope: TaskEnvelope,
    lease_token: str,
) -> BackgroundJob:
    job = db.get(BackgroundJob, envelope.job_id)
    if (
        job is None
        or job.organization_id != envelope.organization_id
        or job.status != "running"
        or job.lease_token != lease_token
    ):
        raise JobEnvelopeError("Background job is not owned by this delivery")
    return job


def _progress(
    envelope: TaskEnvelope,
    lease_token: str,
    *,
    progress: float,
    message: str,
) -> None:
    with _tenant_session(
        envelope.organization_id,
        envelope.actor_principal_id,
    ) as db:
        update_running_job(
            db,
            envelope,
            lease_token,
            progress=progress,
            message=message,
        )


def _generate_golden_dataset(
    envelope: TaskEnvelope,
    lease_token: str,
    heartbeat: JobHeartbeat,
) -> TaskResult:
    _progress(
        envelope,
        lease_token,
        progress=0.15,
        message="Independent annotation and cross-review",
    )
    heartbeat.checkpoint()
    with _tenant_session(
        envelope.organization_id,
        envelope.actor_principal_id,
    ) as db:
        job = _job_or_error(db, envelope, lease_token)
        payload = job.payload
        project = db.get(Project, payload["project_id"])
        document = db.get(Document, payload["document_id"])
        if (
            project is None
            or document is None
            or project.organization_id != envelope.organization_id
            or document.organization_id != envelope.organization_id
        ):
            raise ValueError("Project or document not found")
        dataset = GoldenDatasetService(db, settings, project.id, document).generate(
            profiles=payload["profiles"],
            consensus_profile=payload["consensus_profile"],
            question_count=int(payload["question_count"]),
            language=project.language,
        )
        result = {
            "dataset_id": dataset.id,
            "status": dataset.status,
            "version": dataset.version,
        }
    return result, "Golden Dataset completed"


def _analyze_visual_document(
    envelope: TaskEnvelope,
    lease_token: str,
    heartbeat: JobHeartbeat,
) -> TaskResult:
    _progress(
        envelope,
        lease_token,
        progress=0.15,
        message="Analyzing evidence pages",
    )
    heartbeat.checkpoint()
    with _tenant_session(
        envelope.organization_id,
        envelope.actor_principal_id,
    ) as db:
        job = _job_or_error(db, envelope, lease_token)
        payload = job.payload
        project = db.get(Project, payload["project_id"])
        document = db.get(Document, payload["document_id"])
        if (
            project is None
            or document is None
            or project.organization_id != envelope.organization_id
            or document.organization_id != envelope.organization_id
        ):
            raise ValueError("Project or document not found")
        analyses = VisualEvidenceService(db, settings, project.id).analyze_document(
            document,
            payload["profile"],
            project.language,
            int(payload.get("max_pages") or settings.max_visual_pages),
        )
        result = {
            "analysis_ids": [item.id for item in analyses],
            "count": len(analyses),
        }
    return result, "Visual analysis completed"


def _run_benchmark(
    envelope: TaskEnvelope,
    lease_token: str,
    heartbeat: JobHeartbeat,
) -> TaskResult:
    _progress(
        envelope,
        lease_token,
        progress=0.15,
        message="Running benchmark",
    )
    heartbeat.checkpoint()
    with _tenant_session(
        envelope.organization_id,
        envelope.actor_principal_id,
    ) as db:
        job = _job_or_error(db, envelope, lease_token)
        payload = job.payload
        dataset = db.get(GoldenDataset, payload["dataset_id"])
        if dataset is None or dataset.organization_id != envelope.organization_id:
            raise ValueError("Golden Dataset not found")
        document = db.get(Document, dataset.document_id)
        project = db.get(Project, dataset.project_id)
        if document is None or project is None:
            raise ValueError("Dataset source not found")
        run = BenchmarkService(db, settings, project.id, document, dataset).run(
            profiles=payload["profiles"],
            case_limit=int(payload["case_limit"]),
            run_planner=bool(payload.get("run_planner", True)),
            run_analyzer=bool(payload.get("run_analyzer", True)),
            language=project.language,
        )
        result = {
            "benchmark_id": run.id,
            "winner": run.summary.get("winner"),
        }
    return result, "Benchmark completed"


def _export_learner_memory(
    envelope: TaskEnvelope,
    lease_token: str,
    heartbeat: JobHeartbeat,
) -> TaskResult:
    _progress(
        envelope,
        lease_token,
        progress=0.15,
        message="Building memory export",
    )
    heartbeat.checkpoint()
    with _tenant_session(
        envelope.organization_id,
        envelope.actor_principal_id,
    ) as db:
        job = _job_or_error(db, envelope, lease_token)
        identity = db.get(LearnerIdentity, job.payload["identity_id"])
        if identity is None or identity.organization_id != envelope.organization_id:
            raise ValueError("Learner identity not found")
        result = MemoryControlService(db, settings).export(
            identity,
            include_source_quotes=bool(job.payload.get("include_source_quotes")),
        )
        db.commit()
    return result, "Memory export completed"


def _delete_learner_memory(
    envelope: TaskEnvelope,
    lease_token: str,
    heartbeat: JobHeartbeat,
) -> TaskResult:
    _progress(
        envelope,
        lease_token,
        progress=0.15,
        message="Deleting requested memory scope",
    )
    heartbeat.checkpoint()
    audit_id = ""
    try:
        with _tenant_session(
            envelope.organization_id,
            envelope.actor_principal_id,
        ) as db:
            job = _job_or_error(db, envelope, lease_token)
            audit_id = str(job.payload["audit_id"])
            audit = db.get(MemoryDeletionAudit, audit_id)
            if audit is None or audit.organization_id != envelope.organization_id:
                raise ValueError("Memory deletion audit not found")
            result = MemoryControlService(db, settings).execute_deletion(audit)
            db.commit()
        return result, "Memory deletion completed"
    except Exception as exc:
        if audit_id:
            with _tenant_session(
                envelope.organization_id,
                envelope.actor_principal_id,
            ) as db:
                audit = db.get(MemoryDeletionAudit, audit_id)
                if audit is not None:
                    MemoryControlService(db, settings).mark_deletion_failed(
                        audit,
                        type(exc).__name__,
                    )
                    db.commit()
        raise


TASK_HANDLERS: dict[str, TaskHandler] = {
    "golden_dataset": _generate_golden_dataset,
    "visual_document": _analyze_visual_document,
    "benchmark": _run_benchmark,
    "memory_export": _export_learner_memory,
    "memory_deletion": _delete_learner_memory,
}


def execute_job_delivery(task, envelope_data: dict) -> dict:
    envelope = TaskEnvelope.from_dict(envelope_data)
    delivery_id = str(getattr(task.request, "id", "") or uuid4().hex)
    try:
        with _tenant_session(
            envelope.organization_id,
            envelope.actor_principal_id,
        ) as db:
            claim = claim_job(
                db,
                settings,
                envelope,
                delivery_id=delivery_id,
            )
    except JobAuthorizationError as exc:
        with _tenant_session(
            envelope.organization_id,
            envelope.actor_principal_id,
        ) as db:
            job = db.get(BackgroundJob, envelope.job_id)
            if job is not None and job.organization_id == envelope.organization_id:
                job.status = "failed"
                job.progress = 1.0
                job.error = exc.code
                job.message = "Job authorization denied"
                job.terminal_reason = "authorization_revoked"
                job.completed_at = job.updated_at = datetime.now(UTC)
                append_job_audit(
                    db,
                    job,
                    status="failed",
                    reason_code="authorization_revoked",
                    outcome="denied",
                )
                db.commit()
        raise
    if not claim.execute:
        return {
            "job_id": envelope.job_id,
            "status": claim.status,
            "result": claim.result,
            "duplicate_delivery": True,
        }
    lease_token = str(claim.lease_token)
    heartbeat = JobHeartbeat(
        settings=settings,
        envelope=envelope,
        lease_token=lease_token,
        tenant_session_factory=_tenant_session,
    )
    try:
        with heartbeat:
            heartbeat.checkpoint()
            result, message = TASK_HANDLERS[envelope.kind](
                envelope,
                lease_token,
                heartbeat,
            )
            heartbeat.checkpoint()
        with _tenant_session(
            envelope.organization_id,
            envelope.actor_principal_id,
        ) as db:
            complete_job(
                db,
                envelope,
                lease_token,
                result=result,
                message=message,
            )
        return result
    except Exception as exc:
        with _tenant_session(
            envelope.organization_id,
            envelope.actor_principal_id,
        ) as db:
            disposition = fail_job(
                db,
                settings,
                envelope,
                lease_token,
                exc,
            )
        if disposition.retry:
            raise task.retry(
                exc=exc,
                countdown=disposition.countdown,
                max_retries=settings.job_max_attempts - 1,
            ) from exc
        if isinstance(exc, JobCancelled):
            return {
                "job_id": envelope.job_id,
                "status": "cancelled",
            }
        raise


@celery_app.task(bind=True, name="ai_examiner.generate_golden_dataset")
def generate_golden_dataset_task(task, envelope: dict) -> dict:
    return execute_job_delivery(task, envelope)


@celery_app.task(bind=True, name="ai_examiner.analyze_visual_document")
def analyze_visual_document_task(task, envelope: dict) -> dict:
    return execute_job_delivery(task, envelope)


@celery_app.task(bind=True, name="ai_examiner.run_benchmark")
def run_benchmark_task(task, envelope: dict) -> dict:
    return execute_job_delivery(task, envelope)


@celery_app.task(bind=True, name="ai_examiner.export_learner_memory")
def export_learner_memory_task(task, envelope: dict) -> dict:
    return execute_job_delivery(task, envelope)


@celery_app.task(bind=True, name="ai_examiner.delete_learner_memory")
def delete_learner_memory_task(task, envelope: dict) -> dict:
    return execute_job_delivery(task, envelope)
