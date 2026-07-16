from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from celery import Celery

from .config import get_settings
from .db import SessionLocal, init_db
from .models import BackgroundJob, Document, GoldenDataset, Project
from .services.benchmark import BenchmarkService
from .services.golden import GoldenDatasetService
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


def _update_job(job_id: str, **values: Any) -> None:
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if not job:
            return
        for key, value in values.items():
            setattr(job, key, value)
        db.commit()


@celery_app.task(name="ai_examiner.generate_golden_dataset")
def generate_golden_dataset_task(job_id: str) -> dict:
    init_db()
    _update_job(job_id, status="running", progress=0.05, started_at=utcnow(), message="Loading document")
    try:
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            payload = job.payload
            project = db.get(Project, payload["project_id"])
            document = db.get(Document, payload["document_id"])
            if not project or not document:
                raise ValueError("Project or document not found")
            _update_job(job_id, progress=0.15, message="Independent annotation and cross-review")
            dataset = GoldenDatasetService(db, settings, project.id, document).generate(
                profiles=payload["profiles"],
                consensus_profile=payload["consensus_profile"],
                question_count=int(payload["question_count"]),
                language=project.language,
            )
            result = {"dataset_id": dataset.id, "status": dataset.status, "version": dataset.version}
        _update_job(
            job_id,
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
            status="failed",
            progress=1.0,
            message="Golden Dataset failed",
            error=str(exc),
            completed_at=utcnow(),
        )
        raise


@celery_app.task(name="ai_examiner.analyze_visual_document")
def analyze_visual_document_task(job_id: str) -> dict:
    init_db()
    _update_job(job_id, status="running", progress=0.05, started_at=utcnow(), message="Loading evidence pages")
    try:
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
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
            status="completed",
            progress=1.0,
            message="Visual analysis completed",
            result=result,
            completed_at=utcnow(),
        )
        return result
    except Exception as exc:
        _update_job(job_id, status="failed", progress=1.0, error=str(exc), completed_at=utcnow())
        raise


@celery_app.task(name="ai_examiner.run_benchmark")
def run_benchmark_task(job_id: str) -> dict:
    init_db()
    _update_job(job_id, status="running", progress=0.05, started_at=utcnow(), message="Preparing benchmark")
    try:
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
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
            status="completed",
            progress=1.0,
            message="Benchmark completed",
            result=result,
            completed_at=utcnow(),
        )
        return result
    except Exception as exc:
        _update_job(job_id, status="failed", progress=1.0, error=str(exc), completed_at=utcnow())
        raise
