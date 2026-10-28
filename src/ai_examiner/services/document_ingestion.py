"""Persist uploads before parsing so a mobile request need not wait for previews."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ..config import get_settings
from ..models import BackgroundJob, Document, EvidenceAsset, Project, StoredObject
from .documents import parse_uploaded_document
from .evidence import persist_evidence
from .storage import StorageService, document_object_key
from .tenancy import current_tenant_context

logger = logging.getLogger(__name__)


def document_result(db, document, kind=None):
    assets = list(db.scalars(select(EvidenceAsset.id).where(EvidenceAsset.document_id == document.id)))
    return {"id": document.id, "filename": document.filename,
            "document_kind": kind or Path(document.filename).suffix.lower().lstrip("."),
            "char_count": document.char_count, "page_count": len(document.page_map),
            "evidence_count": len(assets), "warnings": document.parse_warnings,
            "preview": document.content_text[:800]}


def ingestion_receipt(db, project, request_id):
    return db.scalar(select(BackgroundJob).where(
        BackgroundJob.kind == "document_ingestion", BackgroundJob.project_id == project.id,
        BackgroundJob.organization_id == project.organization_id,
        BackgroundJob.actor_principal_id == current_tenant_context(db).principal_id,
        BackgroundJob.idempotency_key == f"{project.id}:{request_id}",
    ))


def queue_document(db, project, *, raw, filename, content_type, request_id, tasks):
    from .jobs import (
        JobIdempotencyConflict,
        JobQueueUnavailable,
        dispatch_job_by_id,
        enqueue_job,
        serialize_job,
    )
    digest = hashlib.sha256(raw).hexdigest()
    old = ingestion_receipt(db, project, request_id)
    if old:
        if old.payload["sha256"] != digest or old.payload["filename"] != filename:
            raise HTTPException(409, "上传编号已用于另一份文件")
        return serialize_job(old, include_internal=False)
    settings = get_settings()
    document_id = str(uuid4())
    storage = StorageService(db, settings)
    stored = storage.store_bytes(
        organization_id=project.organization_id, project_id=project.id,
        resource_type="document", resource_id=document_id, purpose="source",
        object_key=document_object_key(project.organization_id, project.id, document_id,
                                       filename=filename, content_type=content_type),
        data=raw, content_type=content_type,
    )
    staged_key = stored.object_key
    try:
        job = enqueue_job(db, kind="document_ingestion", project_id=project.id,
                          idempotency_key=f"{project.id}:{request_id}", max_attempts=2,
                          dispatch=not settings.celery_always_eager,
                          payload={"document_id": document_id, "stored_id": stored.id,
                                   "filename": filename, "content_type": content_type, "sha256": digest})
    except JobIdempotencyConflict:
        # A concurrent request may already own this receipt. Only discard this
        # request's fresh object, never the source attached to the winning job.
        db.rollback()
        try:
            storage.backend.delete(staged_key)
        except Exception:
            logger.warning("Uncommitted upload cleanup failed; storage reconciliation required")
        job = ingestion_receipt(db, project, request_id)
        if not job or job.payload["sha256"] != digest or job.payload["filename"] != filename:
            raise HTTPException(409, "上传编号已用于另一份文件") from None
    except JobQueueUnavailable:
        job = ingestion_receipt(db, project, request_id)
    else:
        if settings.celery_always_eager:
            tasks.add_task(dispatch_job_by_id, job.id, job.organization_id, job.actor_principal_id)
    return serialize_job(job, include_internal=False)


def execute_document_ingestion(db, job, heartbeat):
    from .session_operations import fence_job
    settings = get_settings()
    payload = job.payload
    project = db.get(Project, job.project_id)
    stored = db.get(StoredObject, payload["stored_id"])
    if not project or not stored or project.organization_id != job.organization_id or (
        stored.organization_id != job.organization_id or stored.project_id != project.id or
        stored.resource_id != payload["document_id"] or stored.status != "active"
    ):
        raise ValueError("Upload scope mismatch")
    existing = db.get(Document, payload["document_id"])
    if existing:
        return {"document": document_result(db, existing)}, "材料已解析"
    storage = StorageService(db, settings)
    raw = storage.read_bytes(stored)
    db.commit()
    heartbeat.checkpoint()
    with TemporaryDirectory(prefix="ingestion-") as directory:
        path = Path(directory) / ("document" + Path(payload["filename"]).suffix.lower())
        path.write_bytes(raw)
        parsed = parse_uploaded_document(path, raw, settings.max_document_chars,
                                         evidence_output_dir=Path(directory) / "evidence",
                                         max_pdf_pages=settings.max_pdf_pages,
                                         timeout_seconds=settings.document_parse_timeout_seconds)
        heartbeat.checkpoint()
        document = Document(id=payload["document_id"], organization_id=job.organization_id,
                            project_id=project.id, filename=payload["filename"],
                            content_type=payload["content_type"], storage_object_id=stored.id,
                            content_text=parsed.text, char_count=len(parsed.text),
                            parse_warnings=parsed.warnings,
                            page_map=[{k: v for k, v in page.items() if k != "preview_path"} for page in parsed.page_map])
        db.add(document)
        db.flush()
        persist_evidence(db, project_id=project.id, document=document, drafts=parsed.evidence, settings=settings)
        fence_job(db, job)
        db.commit()
        return {"document": document_result(db, document, parsed.document_kind)}, "材料已解析"
