from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from celery import Celery

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
    worker_prefetch_multiplier=1,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _tenant_session(organization_id: str, actor_principal_id: str | None):
    db = SessionLocal()
    set_tenant_context(
        db,
        organization_id=organization_id,
        principal_id=actor_principal_id,
    )
    return db


def _update_job(
    job_id: str,
    organization_id: str,
    actor_principal_id: str | None,
    **values: Any,
) -> None:
    with _tenant_session(organization_id, actor_principal_id) as db:
        job = db.get(BackgroundJob, job_id)
        if not job or job.organization_id != organization_id:
            return
        for key, value in values.items():
            setattr(job, key, value)
        db.commit()


@celery_app.task(name="ai_examiner.generate_golden_dataset")
def generate_golden_dataset_task(
    job_id: str,
    organization_id: str,
    actor_principal_id: str | None,
) -> dict:
    _update_job(
        job_id,
        organization_id,
        actor_principal_id,
        status="running",
        progress=0.05,
        started_at=utcnow(),
        message="Loading document",
    )
    try:
        with _tenant_session(organization_id, actor_principal_id) as db:
            job = db.get(BackgroundJob, job_id)
            if not job or job.organization_id != organization_id:
                raise ValueError("Background job not found in tenant")
            payload = job.payload
            project = db.get(Project, payload["project_id"])
            document = db.get(Document, payload["document_id"])
            if not project or not document:
                raise ValueError("Project or document not found")
            _update_job(
                job_id,
                organization_id,
                actor_principal_id,
                progress=0.15,
                message="Independent annotation and cross-review",
            )
            dataset = GoldenDatasetService(db, settings, project.id, document).generate(
                profiles=payload["profiles"],
                consensus_profile=payload["consensus_profile"],
                question_count=int(payload["question_count"]),
                language=project.language,
            )
            result = {"dataset_id": dataset.id, "status": dataset.status, "version": dataset.version}
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="completed",
            progress=1.0,
            message="Golden Dataset completed",
            result=result,
            completed_at=utcnow(),
        )
        return result
    except Exception as exc:
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="failed",
            progress=1.0,
            message="Golden Dataset failed",
            error=str(exc),
            completed_at=utcnow(),
        )
        raise


@celery_app.task(name="ai_examiner.analyze_visual_document")
def analyze_visual_document_task(
    job_id: str,
    organization_id: str,
    actor_principal_id: str | None,
) -> dict:
    _update_job(
        job_id,
        organization_id,
        actor_principal_id,
        status="running",
        progress=0.05,
        started_at=utcnow(),
        message="Loading evidence pages",
    )
    try:
        with _tenant_session(organization_id, actor_principal_id) as db:
            job = db.get(BackgroundJob, job_id)
            if not job or job.organization_id != organization_id:
                raise ValueError("Background job not found in tenant")
            payload = job.payload
            project = db.get(Project, payload["project_id"])
            document = db.get(Document, payload["document_id"])
            if not project or not document:
                raise ValueError("Project or document not found")
            analyses = VisualEvidenceService(db, settings, project.id).analyze_document(
                document,
                payload["profile"],
                project.language,
                int(payload.get("max_pages") or settings.max_visual_pages),
            )
            result = {"analysis_ids": [item.id for item in analyses], "count": len(analyses)}
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="completed",
            progress=1.0,
            message="Visual analysis completed",
            result=result,
            completed_at=utcnow(),
        )
        return result
    except Exception as exc:
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="failed",
            progress=1.0,
            error=str(exc),
            completed_at=utcnow(),
        )
        raise


@celery_app.task(name="ai_examiner.run_benchmark")
def run_benchmark_task(
    job_id: str,
    organization_id: str,
    actor_principal_id: str | None,
) -> dict:
    _update_job(
        job_id,
        organization_id,
        actor_principal_id,
        status="running",
        progress=0.05,
        started_at=utcnow(),
        message="Preparing benchmark",
    )
    try:
        with _tenant_session(organization_id, actor_principal_id) as db:
            job = db.get(BackgroundJob, job_id)
            if not job or job.organization_id != organization_id:
                raise ValueError("Background job not found in tenant")
            payload = job.payload
            dataset = db.get(GoldenDataset, payload["dataset_id"])
            if not dataset:
                raise ValueError("Golden Dataset not found")
            document = db.get(Document, dataset.document_id)
            project = db.get(Project, dataset.project_id)
            if not document or not project:
                raise ValueError("Dataset source not found")
            run = BenchmarkService(db, settings, project.id, document, dataset).run(
                profiles=payload["profiles"],
                case_limit=int(payload["case_limit"]),
                run_planner=bool(payload.get("run_planner", True)),
                run_analyzer=bool(payload.get("run_analyzer", True)),
                language=project.language,
            )
            result = {"benchmark_id": run.id, "winner": run.summary.get("winner")}
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="completed",
            progress=1.0,
            message="Benchmark completed",
            result=result,
            completed_at=utcnow(),
        )
        return result
    except Exception as exc:
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="failed",
            progress=1.0,
            error=str(exc),
            completed_at=utcnow(),
        )
        raise


@celery_app.task(name="ai_examiner.export_learner_memory")
def export_learner_memory_task(
    job_id: str,
    organization_id: str,
    actor_principal_id: str | None,
) -> dict:
    _update_job(
        job_id,
        organization_id,
        actor_principal_id,
        status="running",
        progress=0.1,
        started_at=utcnow(),
        message="Building memory export",
    )
    try:
        with _tenant_session(organization_id, actor_principal_id) as db:
            job = db.get(BackgroundJob, job_id)
            if not job or job.organization_id != organization_id:
                raise ValueError("Background job not found in tenant")
            identity = db.get(LearnerIdentity, job.payload["identity_id"])
            if not identity:
                raise ValueError("Learner identity not found")
            result = MemoryControlService(db, settings).export(
                identity,
                include_source_quotes=bool(job.payload.get("include_source_quotes")),
            )
            db.commit()
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="completed",
            progress=1.0,
            message="Memory export completed",
            result=result,
            completed_at=utcnow(),
        )
        return result
    except Exception as exc:
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="failed",
            progress=1.0,
            message="Memory export failed",
            error=str(exc),
            completed_at=utcnow(),
        )
        raise


@celery_app.task(name="ai_examiner.delete_learner_memory")
def delete_learner_memory_task(
    job_id: str,
    organization_id: str,
    actor_principal_id: str | None,
) -> dict:
    _update_job(
        job_id,
        organization_id,
        actor_principal_id,
        status="running",
        progress=0.1,
        started_at=utcnow(),
        message="Deleting requested memory scope",
    )
    audit_id = ""
    try:
        with _tenant_session(organization_id, actor_principal_id) as db:
            job = db.get(BackgroundJob, job_id)
            if not job or job.organization_id != organization_id:
                raise ValueError("Background job not found in tenant")
            audit_id = str(job.payload["audit_id"])
            audit = db.get(MemoryDeletionAudit, audit_id)
            if not audit:
                raise ValueError("Memory deletion audit not found")
            result = MemoryControlService(db, settings).execute_deletion(audit)
            db.commit()
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="completed",
            progress=1.0,
            message="Memory deletion completed",
            result=result,
            completed_at=utcnow(),
        )
        return result
    except Exception as exc:
        if audit_id:
            with _tenant_session(organization_id, actor_principal_id) as db:
                audit = db.get(MemoryDeletionAudit, audit_id)
                if audit:
                    MemoryControlService(db, settings).mark_deletion_failed(
                        audit, type(exc).__name__
                    )
                    db.commit()
        _update_job(
            job_id,
            organization_id,
            actor_principal_id,
            status="failed",
            progress=1.0,
            message="Memory deletion failed",
            error=str(exc),
            completed_at=utcnow(),
        )
        raise
