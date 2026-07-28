from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import Base
from ..models import (
    DataSubjectRequest,
    HumanReviewCase,
    HumanReviewEvent,
    LearnerIdentity,
    LegalHold,
    MemoryDeletionAudit,
    Organization,
    OrganizationExportArtifact,
    OrganizationMembership,
    OrganizationRetentionPolicy,
    Principal,
    Project,
    StoredObject,
)
from .memory_control import MemoryControlService
from .storage import (
    StorageError,
    StorageObjectMissing,
    StorageService,
    export_object_key,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class DataLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def retention_policy_payload(
    policy: OrganizationRetentionPolicy,
) -> dict[str, Any]:
    return {
        "id": policy.id,
        "organization_id": policy.organization_id,
        "version": policy.version,
        "policy_mode": policy.policy_mode,
        "project_days": policy.project_days,
        "session_days": policy.session_days,
        "document_days": policy.document_days,
        "learner_memory_days": policy.learner_memory_days,
        "export_ttl_hours": policy.export_ttl_hours,
        "deletion_grace_days": policy.deletion_grace_days,
        "policy_digest": policy.policy_digest,
        "updated_by_principal_id": policy.updated_by_principal_id,
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


def _policy_values(values: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "policy_mode": "monitor",
        "project_days": 730,
        "session_days": 365,
        "document_days": 365,
        "learner_memory_days": 365,
        "export_ttl_hours": 24,
        "deletion_grace_days": 7,
        **(values or {}),
    }


def ensure_retention_policy(
    db: Session,
    organization_id: str,
) -> OrganizationRetentionPolicy:
    policy = db.scalar(
        select(OrganizationRetentionPolicy).where(
            OrganizationRetentionPolicy.organization_id == organization_id
        )
    )
    if policy is not None:
        return policy
    values = _policy_values()
    policy = OrganizationRetentionPolicy(
        organization_id=organization_id,
        policy_digest=_digest(values),
        **values,
    )
    db.add(policy)
    db.flush()
    return policy


def update_retention_policy(
    db: Session,
    policy: OrganizationRetentionPolicy,
    values: dict[str, Any],
    *,
    principal_id: str,
) -> OrganizationRetentionPolicy:
    normalized = _policy_values(values)
    for key, value in normalized.items():
        setattr(policy, key, value)
    policy.version += 1
    policy.policy_digest = _digest(normalized)
    policy.updated_by_principal_id = principal_id
    policy.updated_at = utcnow()
    db.flush()
    return policy


def serialize_legal_hold(hold: LegalHold) -> dict[str, Any]:
    return {
        "id": hold.id,
        "organization_id": hold.organization_id,
        "scope_type": hold.scope_type,
        "scope_id": hold.scope_id,
        "reason": hold.reason,
        "status": hold.status,
        "created_by_principal_id": hold.created_by_principal_id,
        "released_by_principal_id": hold.released_by_principal_id,
        "release_reason": hold.release_reason,
        "created_at": hold.created_at.isoformat(),
        "released_at": hold.released_at.isoformat() if hold.released_at else None,
    }


def active_legal_holds(
    db: Session,
    *,
    organization_id: str,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
) -> list[LegalHold]:
    candidates = db.scalars(
        select(LegalHold).where(
            LegalHold.organization_id == organization_id,
            LegalHold.status == "active",
        )
    ).all()
    return [
        hold
        for hold in candidates
        if hold.scope_type == "organization"
        or (
            target_type is not None
            and hold.scope_type == target_type
            and hold.scope_id == target_id
        )
        or (
            request_id is not None
            and hold.scope_type == "data_subject_request"
            and hold.scope_id == request_id
        )
    ]


def serialize_export(artifact: OrganizationExportArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "organization_id": artifact.organization_id,
        "data_subject_request_id": artifact.data_subject_request_id,
        "scope_type": artifact.scope_type,
        "scope_id": artifact.scope_id,
        "include_objects": artifact.include_objects,
        "status": artifact.status,
        "manifest_digest": artifact.manifest_digest,
        "record_counts": artifact.record_counts_json,
        "object_counts": artifact.object_counts_json,
        "failure_code": artifact.failure_code,
        "expires_at": artifact.expires_at.isoformat(),
        "created_at": artifact.created_at.isoformat(),
        "completed_at": (
            artifact.completed_at.isoformat() if artifact.completed_at else None
        ),
        "download_url": (
            f"/api/v1/organization-exports/{artifact.id}/file"
            if artifact.status == "completed"
            else None
        ),
    }


def serialize_data_subject_request(request: DataSubjectRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "organization_id": request.organization_id,
        "request_type": request.request_type,
        "target_type": request.target_type,
        "target_id": request.target_id,
        "requester_principal_id": request.requester_principal_id,
        "reviewer_principal_id": request.reviewer_principal_id,
        "status": request.status,
        "final_decision": request.final_decision or None,
        "decision_reason": request.decision_reason,
        "review_case_id": request.review_case_id,
        "export_artifact_id": request.export_artifact_id,
        "job_id": request.job_id,
        "verification": request.verification_json,
        "deletion_counts": request.deletion_counts_json,
        "blocked_reason": request.blocked_reason,
        "failure_code": request.failure_code,
        "requested_at": request.requested_at.isoformat(),
        "reviewed_at": (
            request.reviewed_at.isoformat() if request.reviewed_at else None
        ),
        "completed_at": (
            request.completed_at.isoformat() if request.completed_at else None
        ),
    }


def serialize_review_case(
    review_case: HumanReviewCase,
    events: list[HumanReviewEvent] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": review_case.id,
        "organization_id": review_case.organization_id,
        "case_type": review_case.case_type,
        "resource_type": review_case.resource_type,
        "resource_id": review_case.resource_id,
        "status": review_case.status,
        "title": review_case.title,
        "summary": review_case.summary,
        "evidence": review_case.evidence_json,
        "created_by_actor_type": review_case.created_by_actor_type,
        "created_by_actor_id": review_case.created_by_actor_id,
        "assigned_principal_id": review_case.assigned_principal_id,
        "final_decision": review_case.final_decision or None,
        "final_decision_by_principal_id": (
            review_case.final_decision_by_principal_id
        ),
        "created_at": review_case.created_at.isoformat(),
        "decided_at": (
            review_case.decided_at.isoformat() if review_case.decided_at else None
        ),
        "closed_at": (
            review_case.closed_at.isoformat() if review_case.closed_at else None
        ),
    }
    if events is not None:
        payload["events"] = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "payload": event.payload_json,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ]
    return payload


class HumanReviewService:
    def __init__(self, db: Session, organization_id: str):
        self.db = db
        self.organization_id = organization_id

    def create(
        self,
        *,
        case_type: str,
        resource_type: str,
        resource_id: str,
        title: str,
        summary: str,
        evidence: list[dict[str, Any]],
        actor_type: str,
        actor_id: str | None,
    ) -> HumanReviewCase:
        review_case = HumanReviewCase(
            organization_id=self.organization_id,
            case_type=case_type,
            resource_type=resource_type,
            resource_id=resource_id,
            title=title,
            summary=summary,
            evidence_json=evidence,
            created_by_actor_type=actor_type,
            created_by_actor_id=actor_id,
        )
        self.db.add(review_case)
        self.db.flush()
        self._event(
            review_case,
            event_type="created",
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"evidence_count": len(evidence)},
        )
        return review_case

    def assign(
        self,
        review_case: HumanReviewCase,
        *,
        reviewer_id: str,
        actor_id: str,
    ) -> HumanReviewCase:
        if review_case.status in {"decided", "closed"}:
            raise DataLifecycleError("review_case_terminal", "Review case is closed")
        review_case.assigned_principal_id = reviewer_id
        review_case.status = "assigned"
        self._event(
            review_case,
            event_type="assigned",
            actor_type="human",
            actor_id=actor_id,
            payload={"assigned_principal_id": reviewer_id},
        )
        self.db.flush()
        return review_case

    def decide(
        self,
        review_case: HumanReviewCase,
        *,
        decision: str,
        reason: str,
        actor_id: str,
    ) -> HumanReviewCase:
        if review_case.status not in {"open", "assigned", "appealed"}:
            raise DataLifecycleError(
                "review_case_terminal", "Review case cannot be decided"
            )
        review_case.final_decision = decision
        review_case.final_decision_by_principal_id = actor_id
        review_case.decided_at = utcnow()
        review_case.status = "decided"
        self._event(
            review_case,
            event_type="decision",
            actor_type="human",
            actor_id=actor_id,
            payload={"decision": decision, "reason": reason},
        )
        self.db.flush()
        return review_case

    def appeal(
        self,
        review_case: HumanReviewCase,
        *,
        reason: str,
        evidence: list[dict[str, Any]],
        actor_id: str,
    ) -> HumanReviewCase:
        if review_case.status not in {"decided", "closed"}:
            raise DataLifecycleError(
                "review_case_not_decided",
                "Only a decided review case can be appealed",
            )
        review_case.status = "appealed"
        review_case.final_decision = ""
        review_case.final_decision_by_principal_id = None
        review_case.decided_at = None
        self._event(
            review_case,
            event_type="appeal",
            actor_type="human",
            actor_id=actor_id,
            payload={"reason": reason, "evidence": evidence},
        )
        self.db.flush()
        return review_case

    def events(self, review_case: HumanReviewCase) -> list[HumanReviewEvent]:
        return list(
            self.db.scalars(
                select(HumanReviewEvent)
                .where(HumanReviewEvent.case_id == review_case.id)
                .order_by(HumanReviewEvent.created_at, HumanReviewEvent.id)
            ).all()
        )

    def _event(
        self,
        review_case: HumanReviewCase,
        *,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        self.db.add(
            HumanReviewEvent(
                organization_id=self.organization_id,
                case_id=review_case.id,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                payload_json=payload,
            )
        )


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def _serialize_row(row: Any) -> dict[str, Any]:
    mapper = inspect(row).mapper
    return {
        column.key: _json_value(getattr(row, column.key))
        for column in mapper.columns
    }


def _tenant_model_classes() -> list[type]:
    result = []
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if "organization_id" in mapper.columns:
            result.append(model)
    return sorted(result, key=lambda item: item.__tablename__)


def _scope_query(model, artifact: OrganizationExportArtifact):
    query = select(model).where(
        model.organization_id == artifact.organization_id
    )
    if artifact.scope_type == "organization":
        return query
    if artifact.scope_type == "project":
        if model is Project:
            return query.where(Project.id == artifact.scope_id)
        if hasattr(model, "project_id"):
            return query.where(model.project_id == artifact.scope_id)
        return None
    if artifact.scope_type == "learner_identity":
        if hasattr(model, "learner_identity_id"):
            return query.where(model.learner_identity_id == artifact.scope_id)
        if model is LearnerIdentity:
            return query.where(LearnerIdentity.id == artifact.scope_id)
        return None
    raise DataLifecycleError("export_scope_invalid", "Unsupported export scope")


def _organization_identity_records(
    db: Session,
    organization_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    memberships = db.scalars(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id
        )
    ).all()
    principal_ids = {membership.principal_id for membership in memberships}
    principals = (
        db.scalars(select(Principal).where(Principal.id.in_(principal_ids))).all()
        if principal_ids
        else []
    )
    return (
        [_serialize_row(item) for item in memberships],
        [
            {
                "id": item.id,
                "issuer": item.issuer,
                "subject": item.subject,
                "display_name": item.display_name,
                "email": item.email,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in principals
        ],
    )


def build_organization_export(
    db: Session,
    settings: Settings,
    artifact: OrganizationExportArtifact,
) -> dict[str, Any]:
    artifact.status = "running"
    artifact.failure_code = ""
    db.flush()
    record_files: dict[str, bytes] = {}
    record_counts: dict[str, int] = {}
    for model in _tenant_model_classes():
        query = _scope_query(model, artifact)
        if query is None:
            continue
        rows = db.scalars(query).all()
        table_name = model.__tablename__
        records = [_serialize_row(row) for row in rows]
        record_counts[table_name] = len(records)
        record_files[f"records/{table_name}.ndjson"] = (
            "\n".join(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                for record in records
            )
            + ("\n" if records else "")
        ).encode("utf-8")
    organization = db.get(Organization, artifact.organization_id)
    if organization is None:
        raise DataLifecycleError(
            "organization_not_found", "Organization is unavailable"
        )
    record_files["records/organization.ndjson"] = (
        json.dumps(_serialize_row(organization), separators=(",", ":")) + "\n"
    ).encode("utf-8")
    record_counts["organizations"] = 1
    if artifact.scope_type == "organization":
        memberships, principals = _organization_identity_records(
            db, artifact.organization_id
        )
        for name, records in (
            ("organization_memberships", memberships),
            ("principals", principals),
        ):
            record_counts[name] = len(records)
            record_files[f"records/{name}.ndjson"] = (
                "\n".join(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                    for record in records
                )
                + ("\n" if records else "")
            ).encode("utf-8")

    object_query = select(StoredObject).where(
        StoredObject.organization_id == artifact.organization_id,
        StoredObject.status == "active",
    )
    if artifact.scope_type == "project":
        object_query = object_query.where(
            StoredObject.project_id == artifact.scope_id
        )
    elif artifact.scope_type == "learner_identity":
        artifact_ids = [
            row["id"]
            for row in (
                json.loads(line)
                for line in record_files.get(
                    "records/memory_export_artifacts.ndjson", b""
                )
                .decode("utf-8")
                .splitlines()
            )
        ]
        if not artifact_ids:
            objects: list[StoredObject] = []
        else:
            object_query = object_query.where(
                StoredObject.resource_type == "memory_export",
                StoredObject.resource_id.in_(artifact_ids),
            )
            objects = list(db.scalars(object_query).all())
    else:
        objects = list(db.scalars(object_query).all())
    if artifact.scope_type != "learner_identity":
        objects = list(db.scalars(object_query).all())

    storage = StorageService(db, settings)
    object_manifest: list[dict[str, Any]] = []
    object_files: dict[str, bytes] = {}
    total_bytes = sum(len(value) for value in record_files.values())
    missing_objects = 0
    for stored in objects:
        entry = {
            "id": stored.id,
            "resource_type": stored.resource_type,
            "resource_id": stored.resource_id,
            "purpose": stored.purpose,
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
            "sha256": stored.sha256,
            "included": False,
            "verified": False,
        }
        try:
            storage.verify(stored)
            entry["verified"] = True
            if artifact.include_objects:
                if total_bytes + stored.size_bytes > settings.organization_export_max_bytes:
                    raise DataLifecycleError(
                        "organization_export_too_large",
                        "Organization export exceeds the configured size limit",
                    )
                data = storage.read_bytes(stored)
                object_files[f"objects/{stored.id}"] = data
                total_bytes += len(data)
                entry["included"] = True
        except (StorageError, StorageObjectMissing):
            missing_objects += 1
            entry["error"] = "object_unavailable"
        object_manifest.append(entry)

    manifest = {
        "schema_version": "organization-export-v1",
        "artifact_id": artifact.id,
        "organization_id": artifact.organization_id,
        "scope": {
            "type": artifact.scope_type,
            "id": artifact.scope_id,
        },
        "generated_at": utcnow().isoformat(),
        "include_objects": artifact.include_objects,
        "record_counts": record_counts,
        "objects": object_manifest,
        "protected_evidence": {
            "audit_events_retained": True,
            "model_usage_ledger_retained": True,
        },
    }
    manifest_digest = _digest(manifest)
    manifest["manifest_digest"] = manifest_digest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        for name, data in {**record_files, **object_files}.items():
            archive.writestr(name, data)
    payload = buffer.getvalue()
    if len(payload) > settings.organization_export_max_bytes:
        raise DataLifecycleError(
            "organization_export_too_large",
            "Organization export exceeds the configured size limit",
        )
    stored = storage.store_bytes(
        organization_id=artifact.organization_id,
        project_id=None,
        resource_type="organization_export",
        resource_id=artifact.id,
        purpose="export",
        object_key=export_object_key(
            artifact.organization_id,
            artifact.id,
            content_type="application/zip",
        ),
        data=payload,
        content_type="application/zip",
    )
    artifact.storage_object_id = stored.id
    artifact.manifest_digest = manifest_digest
    artifact.record_counts_json = record_counts
    artifact.object_counts_json = {
        "total": len(objects),
        "included": len(object_files),
        "missing": missing_objects,
        "bytes": sum(len(value) for value in object_files.values()),
    }
    artifact.status = "completed"
    artifact.completed_at = utcnow()
    db.flush()
    return serialize_export(artifact)


def export_artifact_or_error(
    db: Session,
    settings: Settings,
    artifact_id: str,
) -> tuple[OrganizationExportArtifact, StoredObject]:
    artifact = db.get(OrganizationExportArtifact, artifact_id)
    if artifact is None:
        raise DataLifecycleError("export_not_found", "Export not found")
    if _as_utc(artifact.expires_at) <= utcnow():
        artifact.status = "expired"
        if artifact.storage_object_id:
            stored = db.get(StoredObject, artifact.storage_object_id)
            if stored is not None and stored.status == "active":
                StorageService(db, settings).delete(stored)
        db.flush()
        raise DataLifecycleError("export_expired", "Export has expired")
    stored = (
        db.get(StoredObject, artifact.storage_object_id)
        if artifact.storage_object_id
        else None
    )
    if artifact.status != "completed" or stored is None or stored.status != "active":
        raise DataLifecycleError("export_unavailable", "Export is unavailable")
    StorageService(db, settings).verify(stored)
    return artifact, stored


class DataSubjectRequestService:
    def __init__(self, db: Session, settings: Settings, organization_id: str):
        self.db = db
        self.settings = settings
        self.organization_id = organization_id

    def validate_target(self, target_type: str, target_id: str) -> None:
        if target_type == "project":
            target = self.db.get(Project, target_id)
        elif target_type == "learner_identity":
            target = self.db.get(LearnerIdentity, target_id)
        else:
            target = None
        if target is None or target.organization_id != self.organization_id:
            raise DataLifecycleError("target_not_found", "Request target not found")

    def create(
        self,
        *,
        request_type: str,
        target_type: str,
        target_id: str,
        requester_id: str,
        idempotency_key: str,
        reason: str,
    ) -> DataSubjectRequest:
        self.validate_target(target_type, target_id)
        existing = self.db.scalar(
            select(DataSubjectRequest).where(
                DataSubjectRequest.organization_id == self.organization_id,
                DataSubjectRequest.requester_principal_id == requester_id,
                DataSubjectRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.request_type != request_type
                or existing.target_type != target_type
                or existing.target_id != target_id
            ):
                raise DataLifecycleError(
                    "idempotency_conflict",
                    "Idempotency key was reused with different request data",
                )
            return existing
        request = DataSubjectRequest(
            organization_id=self.organization_id,
            request_type=request_type,
            target_type=target_type,
            target_id=target_id,
            requester_principal_id=requester_id,
            idempotency_key=idempotency_key,
            decision_reason=reason,
        )
        self.db.add(request)
        self.db.flush()
        review = HumanReviewService(self.db, self.organization_id).create(
            case_type="data_subject_request",
            resource_type="data_subject_request",
            resource_id=request.id,
            title=f"{request_type.title()} request for {target_type}",
            summary=reason,
            evidence=[],
            actor_type="human",
            actor_id=requester_id,
        )
        request.review_case_id = review.id
        self.db.flush()
        return request

    def decide(
        self,
        request: DataSubjectRequest,
        *,
        decision: str,
        reason: str,
        reviewer_id: str,
        idempotency_key: str,
    ) -> DataSubjectRequest:
        if request.decision_idempotency_key == idempotency_key:
            if (
                request.final_decision != decision
                or request.reviewer_principal_id != reviewer_id
            ):
                raise DataLifecycleError(
                    "idempotency_conflict",
                    "Decision idempotency key was reused with different data",
                )
            return request
        if request.status != "requested":
            raise DataLifecycleError(
                "request_not_pending", "Request is not pending review"
            )
        if request.request_type == "delete" and (
            reviewer_id == request.requester_principal_id
        ):
            raise DataLifecycleError(
                "dual_control_required",
                "Deletion approval requires a different reviewer",
            )
        review_case = self.db.get(HumanReviewCase, request.review_case_id)
        if review_case is None:
            raise DataLifecycleError(
                "review_case_missing", "Request review case is unavailable"
            )
        HumanReviewService(self.db, self.organization_id).decide(
            review_case,
            decision=decision,
            reason=reason,
            actor_id=reviewer_id,
        )
        request.reviewer_principal_id = reviewer_id
        request.reviewed_at = utcnow()
        request.final_decision = decision
        request.decision_idempotency_key = idempotency_key
        request.decision_reason = reason
        request.status = "approved" if decision == "approved" else "denied"
        if decision == "denied":
            request.completed_at = utcnow()
        self.db.flush()
        return request

    def cancel(
        self,
        request: DataSubjectRequest,
        *,
        actor_id: str,
        reason: str,
    ) -> DataSubjectRequest:
        if request.status not in {"requested", "approved", "blocked", "failed"}:
            raise DataLifecycleError(
                "request_not_cancellable", "Request cannot be cancelled"
            )
        if actor_id not in {
            request.requester_principal_id,
            request.reviewer_principal_id,
        }:
            raise DataLifecycleError(
                "request_cancel_denied", "Request cannot be cancelled by this actor"
            )
        request.status = "cancelled"
        request.final_decision = "cancelled"
        request.decision_reason = reason
        request.completed_at = utcnow()
        self.db.flush()
        return request

    def execute_deletion(self, request: DataSubjectRequest) -> dict[str, Any]:
        if request.request_type != "delete" or request.status not in {
            "approved",
            "failed",
            "blocked",
        }:
            raise DataLifecycleError(
                "request_not_executable", "Deletion request is not executable"
            )
        holds = active_legal_holds(
            self.db,
            organization_id=self.organization_id,
            target_type=request.target_type,
            target_id=request.target_id,
            request_id=request.id,
        )
        if holds:
            request.status = "blocked"
            request.blocked_reason = "legal_hold"
            request.verification_json = {
                "legal_hold_ids": [hold.id for hold in holds],
            }
            self.db.flush()
            return serialize_data_subject_request(request)
        request.status = "running"
        request.blocked_reason = ""
        self.db.flush()
        if request.target_type == "project":
            counts, verification = self._delete_project(request.target_id)
        else:
            counts, verification = self._delete_learner_identity(
                request.target_id
            )
        request.status = "verifying"
        request.deletion_counts_json = counts
        request.verification_json = verification
        self.db.flush()
        if not verification.get("verified"):
            raise DataLifecycleError(
                "deletion_verification_failed",
                "Deletion verification did not converge",
            )
        request.status = "completed"
        request.completed_at = utcnow()
        request.failure_code = ""
        self.db.flush()
        return serialize_data_subject_request(request)

    def mark_failed(self, request: DataSubjectRequest, code: str) -> None:
        request.status = "failed"
        request.failure_code = code[:120]
        self.db.flush()

    def _delete_project(
        self, project_id: str
    ) -> tuple[dict[str, int], dict[str, Any]]:
        project = self.db.get(Project, project_id)
        if project is None or project.organization_id != self.organization_id:
            return (
                {"projects": 0, "objects": 0},
                {"verified": True, "relational_remaining": 0, "objects_remaining": 0},
            )
        storage = StorageService(self.db, self.settings)
        objects = self.db.scalars(
            select(StoredObject).where(
                StoredObject.organization_id == self.organization_id,
                StoredObject.project_id == project_id,
                StoredObject.status == "active",
            )
        ).all()
        deleted_object_ids: list[str] = []
        for stored in objects:
            storage.delete(stored)
            if storage.backend_for(stored).exists(stored.object_key):
                raise DataLifecycleError(
                    "object_delete_verification_failed",
                    "A project object still exists after deletion",
                )
            stored.project_id = None
            deleted_object_ids.append(stored.id)
        self.db.delete(project)
        self.db.flush()
        relational_remaining = int(
            self.db.scalar(
                select(func.count(Project.id)).where(Project.id == project_id)
            )
            or 0
        )
        objects_remaining = sum(
            1
            for object_id in deleted_object_ids
            if (
                (stored := self.db.get(StoredObject, object_id)) is not None
                and storage.backend_for(stored).exists(stored.object_key)
            )
        )
        return (
            {"projects": 1, "objects": len(deleted_object_ids)},
            {
                "verified": relational_remaining == 0 and objects_remaining == 0,
                "relational_remaining": relational_remaining,
                "objects_remaining": objects_remaining,
                "protected_audit_retained": True,
                "protected_usage_retained": True,
            },
        )

    def _delete_learner_identity(
        self, identity_id: str
    ) -> tuple[dict[str, int], dict[str, Any]]:
        identity = self.db.get(LearnerIdentity, identity_id)
        if identity is None or identity.organization_id != self.organization_id:
            return (
                {"identities": 0},
                {"verified": True, "relational_remaining": 0},
            )
        audit = MemoryDeletionAudit(
            organization_id=self.organization_id,
            learner_identity_id=identity.id,
            scope="identity_and_memory",
            status="pending",
        )
        identity.memory_write_blocked = True
        self.db.add(audit)
        self.db.flush()
        result = MemoryControlService(self.db, self.settings).execute_deletion(audit)
        self.db.flush()
        remaining = int(
            self.db.scalar(
                select(func.count(LearnerIdentity.id)).where(
                    LearnerIdentity.id == identity_id
                )
            )
            or 0
        )
        return (
            {key: int(value) for key, value in result["counts"].items()},
            {
                "verified": remaining == 0,
                "relational_remaining": remaining,
                "memory_deletion_audit_id": audit.id,
                "protected_audit_retained": True,
            },
        )
