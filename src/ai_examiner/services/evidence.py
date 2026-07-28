from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Document, EvidenceAsset
from .documents import EvidenceDraft
from .storage import StorageService, evidence_object_key


def persist_evidence(
    db: Session,
    *,
    project_id: str,
    document: Document,
    drafts: Iterable[EvidenceDraft],
    settings: Settings | None = None,
) -> list[EvidenceAsset]:
    db.execute(delete(EvidenceAsset).where(EvidenceAsset.document_id == document.id))
    storage = StorageService(db, settings) if settings is not None else None
    assets: list[EvidenceAsset] = []
    for draft in drafts:
        asset = EvidenceAsset(
            organization_id=document.organization_id,
            project_id=project_id,
            document_id=document.id,
            kind=draft.kind,
            page_number=draft.page_number,
            sequence=draft.sequence,
            label=draft.label,
            text=draft.text,
            bbox=draft.bbox,
            metadata_json=draft.metadata,
            storage_path=draft.storage_path,
            mime_type=draft.mime_type,
            sha256=draft.sha256,
        )
        db.add(asset)
        db.flush()
        if storage is not None and draft.storage_path:
            source = Path(draft.storage_path)
            if source.is_file():
                data = source.read_bytes()
                stored = storage.store_bytes(
                    organization_id=document.organization_id,
                    project_id=project_id,
                    resource_type="evidence_asset",
                    resource_id=asset.id,
                    purpose=draft.kind,
                    object_key=evidence_object_key(
                        document.organization_id,
                        project_id,
                        asset.id,
                        kind=draft.kind,
                        page_number=draft.page_number,
                        sequence=draft.sequence,
                        filename=source.name,
                        content_type=draft.mime_type,
                    ),
                    data=data,
                    content_type=draft.mime_type or "application/octet-stream",
                )
                asset.storage_object_id = stored.id
                asset.storage_path = None
        assets.append(asset)
    db.flush()
    return assets


def serialize_asset(asset: EvidenceAsset) -> dict:
    return {
        "id": asset.id,
        "document_id": asset.document_id,
        "kind": asset.kind,
        "page_number": asset.page_number,
        "sequence": asset.sequence,
        "label": asset.label,
        "text": asset.text,
        "bbox": asset.bbox,
        "metadata": asset.metadata_json,
        "mime_type": asset.mime_type,
        "has_file": bool(asset.storage_object_id or asset.storage_path),
        "file_url": (
            f"/api/evidence/{asset.id}/file"
            if asset.storage_object_id or asset.storage_path
            else None
        ),
        "authorized_file_url": (
            f"/api/v1/evidence/{asset.id}/file"
            if asset.storage_object_id or asset.storage_path
            else None
        ),
        "authorized_highlight_url": f"/api/v1/evidence/{asset.id}/highlight",
        "created_at": asset.created_at.isoformat(),
    }


def page_assets(db: Session, document_id: str) -> list[EvidenceAsset]:
    return list(
        db.scalars(
            select(EvidenceAsset)
            .where(EvidenceAsset.document_id == document_id)
            .order_by(EvidenceAsset.page_number, EvidenceAsset.sequence)
        ).all()
    )


def create_highlighted_crop(
    asset: EvidenceAsset,
    page_asset: EvidenceAsset,
    output_dir: Path,
) -> Path:
    if not page_asset.storage_path:
        raise ValueError("Page preview is unavailable")
    source = Path(page_asset.storage_path)
    if not source.exists():
        raise ValueError("Page preview file is missing")
    image = Image.open(source).convert("RGB")
    bbox = asset.bbox or []
    if len(bbox) != 4:
        return source
    meta = page_asset.metadata_json or {}
    page_width = float(meta.get("width") or 1)
    page_height = float(meta.get("height") or 1)
    if max(bbox) <= 1.0:
        left, top, right, bottom = (
            int(bbox[0] * image.width),
            int(bbox[1] * image.height),
            int(bbox[2] * image.width),
            int(bbox[3] * image.height),
        )
    else:
        left, top, right, bottom = (
            int(bbox[0] / page_width * image.width),
            int(bbox[1] / page_height * image.height),
            int(bbox[2] / page_width * image.width),
            int(bbox[3] / page_height * image.height),
        )
    pad = 20
    left, top = max(0, left - pad), max(0, top - pad)
    right, bottom = min(image.width, right + pad), min(image.height, bottom + pad)
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, top, right, bottom), outline="red", width=max(3, image.width // 400))
    crop = image.crop((left, top, right, bottom))
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{asset.id}:{asset.sha256}".encode()).hexdigest()[:16]
    output = output_dir / f"evidence-{asset.id}-{digest}.png"
    crop.save(output, "PNG")
    return output
