from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Document, EvidenceAsset, MemoryExportArtifact, StoredObject
from .storage import (
    StorageError,
    StorageObjectMissing,
    StorageService,
    document_object_key,
    evidence_object_key,
    export_object_key,
)


def _checkpoint(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _resource_rows(db: Session):
    yield from db.scalars(
        select(Document).order_by(Document.created_at, Document.id)
    ).all()
    yield from db.scalars(
        select(EvidenceAsset).order_by(EvidenceAsset.created_at, EvidenceAsset.id)
    ).all()
    yield from db.scalars(
        select(MemoryExportArtifact).order_by(
            MemoryExportArtifact.created_at,
            MemoryExportArtifact.id,
        )
    ).all()


def _resource_descriptor(row) -> tuple[str, str | None, str, str, str]:
    source = Path(row.storage_path or "")
    if isinstance(row, Document):
        return (
            "document",
            row.project_id,
            "source",
            document_object_key(
                row.organization_id,
                row.project_id,
                row.id,
                filename=row.filename,
                content_type=row.content_type,
            ),
            row.content_type,
        )
    if isinstance(row, EvidenceAsset):
        return (
            "evidence_asset",
            row.project_id,
            row.kind,
            evidence_object_key(
                row.organization_id,
                row.project_id,
                row.id,
                kind=row.kind,
                page_number=row.page_number,
                sequence=row.sequence,
                filename=source.name,
                content_type=row.mime_type,
            ),
            row.mime_type or "application/octet-stream",
        )
    return (
        "memory_export",
        None,
        "export",
        export_object_key(row.organization_id, row.id),
        "application/json",
    )


def migrate_legacy_storage(
    db: Session,
    settings: Settings,
    *,
    checkpoint_path: Path,
    delete_source: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "version": "storage-migration-v1",
        "backend": settings.storage_backend,
        "bucket": settings.s3_bucket or "",
        "completed": {},
        "skipped": {},
        "failed": {},
    }
    if checkpoint_path.exists():
        prior = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            prior.get("backend") != report["backend"]
            or prior.get("bucket", "") != report["bucket"]
        ):
            raise StorageError("Checkpoint targets a different storage backend")
        for key in ("completed", "skipped", "failed"):
            report[key].update(prior.get(key) or {})

    storage = StorageService(db, settings)
    processed = 0
    for row in _resource_rows(db):
        if limit is not None and processed >= limit:
            break
        resource_key = f"{row.__tablename__}:{row.id}"
        if row.storage_object_id:
            stored = db.get(StoredObject, row.storage_object_id)
            if stored is not None:
                try:
                    storage.verify(stored)
                    report["completed"][resource_key] = {
                        "object_key": stored.object_key,
                        "sha256": stored.sha256,
                        "size_bytes": stored.size_bytes,
                        "resumed": True,
                    }
                    report["failed"].pop(resource_key, None)
                    _checkpoint(checkpoint_path, report)
                    continue
                except StorageError:
                    pass
        if not row.storage_path:
            report["skipped"][resource_key] = "no_legacy_path"
            _checkpoint(checkpoint_path, report)
            continue
        source = Path(row.storage_path).expanduser().resolve()
        if not source.is_file():
            report["failed"][resource_key] = "source_missing"
            _checkpoint(checkpoint_path, report)
            continue

        data = source.read_bytes()
        resource_type, project_id, purpose, object_key, content_type = (
            _resource_descriptor(row)
        )
        expected_sha256 = hashlib.sha256(data).hexdigest()
        if dry_run:
            report["skipped"][resource_key] = {
                "reason": "dry_run",
                "object_key": object_key,
                "sha256": expected_sha256,
                "size_bytes": len(data),
            }
            continue
        try:
            stored = storage.store_bytes(
                organization_id=row.organization_id,
                project_id=project_id,
                resource_type=resource_type,
                resource_id=row.id,
                purpose=purpose,
                object_key=object_key,
                data=data,
                content_type=content_type,
            )
            storage.verify(stored)
            row.storage_object_id = stored.id
            row.storage_path = None
            db.commit()
            if delete_source:
                target = storage.backend.local_path(stored.object_key)
                if target is None or target.resolve() != source:
                    source.unlink(missing_ok=True)
            report["completed"][resource_key] = {
                "object_key": stored.object_key,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
                "resumed": False,
            }
            report["failed"].pop(resource_key, None)
            processed += 1
        except Exception as exc:
            db.rollback()
            report["failed"][resource_key] = type(exc).__name__
        _checkpoint(checkpoint_path, report)

    report["summary"] = {
        "completed": len(report["completed"]),
        "skipped": len(report["skipped"]),
        "failed": len(report["failed"]),
    }
    _checkpoint(checkpoint_path, report)
    return report


def reconcile_storage(db: Session, settings: Settings) -> dict[str, Any]:
    storage = StorageService(db, settings)
    report: dict[str, Any] = {
        "version": "storage-reconciliation-v1",
        "verified": {},
        "missing": {},
        "mismatched": {},
    }
    for stored in db.scalars(
        select(StoredObject).where(StoredObject.status != "deleted")
    ).all():
        key = stored.id
        try:
            storage.verify(stored)
            stored.status = "active"
            report["verified"][key] = stored.object_key
        except StorageObjectMissing:
            stored.status = "missing"
            report["missing"][key] = stored.object_key
        except StorageError as exc:
            report["mismatched"][key] = str(exc)
    db.commit()
    report["summary"] = {
        "verified": len(report["verified"]),
        "missing": len(report["missing"]),
        "mismatched": len(report["mismatched"]),
    }
    return report
