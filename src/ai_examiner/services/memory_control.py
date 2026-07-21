from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    LearnerConceptState,
    LearnerIdentity,
    LearnerIdentityLink,
    LearnerMemoryEvent,
    LearnerPreference,
    MemoryDeletionAudit,
    MemoryExportArtifact,
    RetestItem,
    RetestPlan,
)
from .longitudinal import LongitudinalStateService
from .preferences import PreferenceService


class MemoryControlError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class MemoryControlService:
    export_version = "memory-export-v1"
    deletion_policy_version = "memory-deletion-v1"

    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings

    def correct_event(
        self,
        identity: LearnerIdentity,
        event: LearnerMemoryEvent,
        *,
        observation: float,
        reason: str,
    ) -> LearnerMemoryEvent:
        self._assert_writable(identity)
        if event.learner_identity_id != identity.id or not event.concept_id:
            raise MemoryControlError("Memory event is not correctable for this identity")
        if event.event_type not in {
            "concept_evidence",
            "concept_correction",
            "retest_outcome",
        }:
            raise MemoryControlError("Only concept evidence can be corrected")
        if self.db.scalar(
            select(func.count(LearnerMemoryEvent.id)).where(
                LearnerMemoryEvent.supersedes_event_id == event.id,
                LearnerMemoryEvent.deleted_at.is_(None),
            )
        ):
            raise MemoryControlError("Memory event has already been superseded")
        payload = dict(event.payload_json or {})
        payload.update(
            {
                "observation": observation,
                "correction_reason": reason.strip(),
                "corrected_event_type": event.event_type,
            }
        )
        correction = LearnerMemoryEvent(
            learner_identity_id=identity.id,
            learner_subject_id=event.learner_subject_id,
            concept_id=event.concept_id,
            event_type="concept_correction",
            payload_json=payload,
            occurred_at=utcnow(),
            policy_version="memory-correction-v1",
            algorithm_version="memory-ledger-v1",
            supersedes_event_id=event.id,
        )
        self.db.add(correction)
        self.db.flush()
        algorithm = self.db.scalar(
            select(LearnerConceptState.algorithm_version).where(
                LearnerConceptState.learner_identity_id == identity.id
            )
        ) or "evidence-half-life-v1"
        LongitudinalStateService(self.db).rebuild(
            identity, algorithm_version=algorithm, dry_run=False
        )
        self.db.flush()
        return correction

    def export(self, identity: LearnerIdentity, *, include_source_quotes: bool) -> dict:
        events = self.db.scalars(
            select(LearnerMemoryEvent)
            .where(
                LearnerMemoryEvent.learner_identity_id == identity.id,
                LearnerMemoryEvent.deleted_at.is_(None),
            )
            .order_by(LearnerMemoryEvent.occurred_at, LearnerMemoryEvent.id)
        ).all()
        links = self.db.scalars(
            select(LearnerIdentityLink).where(
                LearnerIdentityLink.learner_identity_id == identity.id
            )
        ).all()
        preferences = PreferenceService(self.db).list(identity)
        states = LongitudinalStateService(self.db).states(identity)
        plans = LongitudinalStateService(self.db).plans(identity)
        payload = {
            "export_version": self.export_version,
            "generated_at": utcnow().isoformat(),
            "identity": {
                "id": identity.id,
                "display_name": identity.display_name,
                "memory_enabled": identity.memory_enabled,
                "memory_scope": identity.memory_scope,
                "policy_version": identity.policy_version,
            },
            "links": [
                {
                    "id": link.id,
                    "learner_subject_id": link.learner_subject_id,
                    "status": link.status,
                    "provenance": link.provenance,
                    "created_at": link.created_at.isoformat(),
                    "revoked_at": link.revoked_at.isoformat()
                    if link.revoked_at
                    else None,
                }
                for link in links
            ],
            "events": [self._serialize_event(event, include_source_quotes) for event in events],
            "concept_states": states,
            "preferences": preferences,
            "retest_plans": plans,
        }
        counts = {
            "links": len(links),
            "events": len(events),
            "concept_states": len(states),
            "preferences": len(preferences),
            "retest_plans": len(plans),
        }
        export_root = (self.settings.export_dir / "memory").resolve()
        export_root.mkdir(parents=True, exist_ok=True)
        artifact = MemoryExportArtifact(
            learner_identity_id=identity.id,
            storage_path="",
            scope_json={"include_source_quotes": include_source_quotes},
            record_counts=counts,
            expires_at=utcnow() + timedelta(hours=24),
        )
        self.db.add(artifact)
        self.db.flush()
        path = (export_root / f"{artifact.id}.json").resolve()
        self._assert_under_export_root(path)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact.storage_path = str(path)
        self.db.flush()
        return self.serialize_artifact(artifact)

    def begin_deletion(
        self,
        identity: LearnerIdentity,
        *,
        scope: str,
        target_ref: str | None,
    ) -> MemoryDeletionAudit:
        if identity.memory_write_blocked:
            raise MemoryControlError("A memory deletion is already pending")
        audit = MemoryDeletionAudit(
            learner_identity_id=identity.id,
            scope=scope,
            target_ref=target_ref,
            status="pending",
        )
        identity.memory_write_blocked = True
        self.db.add(audit)
        self.db.flush()
        return audit

    def execute_deletion(self, audit: MemoryDeletionAudit) -> dict:
        identity = (
            self.db.get(LearnerIdentity, audit.learner_identity_id)
            if audit.learner_identity_id
            else None
        )
        if not identity:
            raise MemoryControlError("Learner identity no longer exists")
        audit.status = "running"
        counts: dict[str, int] = {}
        scope = audit.scope
        target = audit.target_ref
        if scope == "preference":
            preference = self.db.get(LearnerPreference, target) if target else None
            if not preference or preference.learner_identity_id != identity.id:
                raise MemoryControlError("Preference not found")
            preference_key = preference.preference_key
            self.db.delete(preference)
            counts["preferences"] = 1
            counts["events"] = self._delete_preference_events(identity.id, preference_key)
        elif scope == "concept":
            if not target:
                raise MemoryControlError("Concept deletion requires concept_id")
            counts["events"] = self._delete_rows(
                LearnerMemoryEvent,
                LearnerMemoryEvent.learner_identity_id == identity.id,
                LearnerMemoryEvent.concept_id == target,
            )
            counts["states"] = self._delete_rows(
                LearnerConceptState,
                LearnerConceptState.learner_identity_id == identity.id,
                LearnerConceptState.concept_id == target,
            )
            counts["retest_items"] = self._delete_retest_items(identity.id, target)
            self._delete_empty_plans(identity.id)
        elif scope == "project_link":
            if not target:
                raise MemoryControlError("Project-link deletion requires learner_subject_id")
            link = self.db.scalar(
                select(LearnerIdentityLink).where(
                    LearnerIdentityLink.learner_identity_id == identity.id,
                    LearnerIdentityLink.learner_subject_id == target,
                )
            )
            if not link:
                raise MemoryControlError("Project link not found")
            counts["events"] = self._delete_rows(
                LearnerMemoryEvent,
                LearnerMemoryEvent.learner_identity_id == identity.id,
                LearnerMemoryEvent.learner_subject_id == target,
            )
            self.db.delete(link)
            counts["links"] = 1
            counts["retest_plans"] = self._delete_rows(
                RetestPlan, RetestPlan.learner_identity_id == identity.id
            )
            LongitudinalStateService(self.db).rebuild(
                identity,
                algorithm_version="evidence-half-life-v1",
                dry_run=False,
            )
        elif scope in {"all_long_term_memory", "identity_and_memory"}:
            counts["events"] = self._delete_rows(
                LearnerMemoryEvent,
                LearnerMemoryEvent.learner_identity_id == identity.id,
            )
            counts["states"] = self._delete_rows(
                LearnerConceptState,
                LearnerConceptState.learner_identity_id == identity.id,
            )
            counts["retest_plans"] = self._delete_rows(
                RetestPlan, RetestPlan.learner_identity_id == identity.id
            )
            counts["preferences"] = self._delete_rows(
                LearnerPreference, LearnerPreference.learner_identity_id == identity.id
            )
            counts["artifacts"] = self._delete_artifacts(identity.id)
            if scope == "all_long_term_memory":
                identity.memory_enabled = False
            else:
                counts["links"] = self._delete_rows(
                    LearnerIdentityLink,
                    LearnerIdentityLink.learner_identity_id == identity.id,
                )
                self.db.flush()
                self.db.delete(identity)
                counts["identities"] = 1
        else:
            raise MemoryControlError("Unsupported deletion scope")

        if scope not in {"all_long_term_memory", "identity_and_memory"}:
            counts["artifacts"] = self._delete_artifacts(identity.id)
            if scope != "project_link":
                LongitudinalStateService(self.db).rebuild(
                    identity,
                    algorithm_version="evidence-half-life-v1",
                    dry_run=False,
                )
        if scope != "identity_and_memory":
            identity.memory_write_blocked = False
        audit.counts_json = counts
        audit.status = "completed"
        audit.completed_at = utcnow()
        self.db.flush()
        return {"audit_id": audit.id, "scope": scope, "counts": counts}

    def mark_deletion_failed(self, audit: MemoryDeletionAudit, error_code: str) -> None:
        audit.status = "failed"
        audit.error_code = error_code[:100]
        audit.completed_at = utcnow()
        self.db.flush()

    def artifact_or_error(self, artifact_id: str) -> MemoryExportArtifact:
        artifact = self.db.get(MemoryExportArtifact, artifact_id)
        if not artifact:
            raise MemoryControlError("Memory export not found")
        if ensure_utc(artifact.expires_at) <= utcnow():
            self._remove_artifact_file(artifact)
            self.db.delete(artifact)
            self.db.flush()
            raise MemoryControlError("Memory export has expired")
        path = Path(artifact.storage_path).resolve()
        self._assert_under_export_root(path)
        if not path.exists():
            raise MemoryControlError("Memory export file is unavailable")
        return artifact

    @staticmethod
    def serialize_artifact(artifact: MemoryExportArtifact) -> dict:
        return {
            "id": artifact.id,
            "learner_identity_id": artifact.learner_identity_id,
            "record_counts": artifact.record_counts,
            "expires_at": artifact.expires_at.isoformat(),
            "created_at": artifact.created_at.isoformat(),
            "download_url": f"/api/memory-exports/{artifact.id}/file",
        }

    @staticmethod
    def _serialize_event(event: LearnerMemoryEvent, include_source_quotes: bool) -> dict:
        payload = dict(event.payload_json or {})
        if not include_source_quotes:
            payload.pop("answer_quote", None)
            payload.pop("content", None)
        return {
            "id": event.id,
            "event_type": event.event_type,
            "learner_subject_id": event.learner_subject_id,
            "concept_id": event.concept_id,
            "source_evidence_event_id": event.source_evidence_event_id,
            "payload": payload,
            "occurred_at": event.occurred_at.isoformat(),
            "policy_version": event.policy_version,
            "algorithm_version": event.algorithm_version,
            "supersedes_event_id": event.supersedes_event_id,
        }

    def _delete_preference_events(self, identity_id: str, preference_key: str) -> int:
        events = self.db.scalars(
            select(LearnerMemoryEvent).where(
                LearnerMemoryEvent.learner_identity_id == identity_id,
                LearnerMemoryEvent.event_type.in_(
                    ["explicit_preference", "confirmed_preference"]
                ),
            )
        ).all()
        selected = [
            event
            for event in events
            if (event.payload_json or {}).get("preference_key") == preference_key
        ]
        for event in selected:
            self.db.delete(event)
        return len(selected)

    def _delete_retest_items(self, identity_id: str, concept_id: str) -> int:
        items = self.db.scalars(
            select(RetestItem)
            .join(RetestPlan, RetestPlan.id == RetestItem.retest_plan_id)
            .where(
                RetestPlan.learner_identity_id == identity_id,
                RetestItem.concept_id == concept_id,
            )
        ).all()
        for item in items:
            self.db.delete(item)
        return len(items)

    def _delete_empty_plans(self, identity_id: str) -> None:
        self.db.flush()
        plans = self.db.scalars(
            select(RetestPlan).where(RetestPlan.learner_identity_id == identity_id)
        ).all()
        for plan in plans:
            count = self.db.scalar(
                select(func.count(RetestItem.id)).where(
                    RetestItem.retest_plan_id == plan.id
                )
            )
            if not count:
                self.db.delete(plan)

    def _delete_artifacts(self, identity_id: str) -> int:
        artifacts = self.db.scalars(
            select(MemoryExportArtifact).where(
                MemoryExportArtifact.learner_identity_id == identity_id
            )
        ).all()
        for artifact in artifacts:
            self._remove_artifact_file(artifact)
            self.db.delete(artifact)
        return len(artifacts)

    def _remove_artifact_file(self, artifact: MemoryExportArtifact) -> None:
        path = Path(artifact.storage_path).resolve()
        self._assert_under_export_root(path)
        if path.exists() and path.is_file():
            path.unlink()

    def _assert_under_export_root(self, path: Path) -> None:
        root = self.settings.export_dir.resolve()
        if root != path and root not in path.parents:
            raise MemoryControlError("Invalid memory export path")

    def _delete_rows(self, model, *conditions) -> int:
        result = self.db.execute(delete(model).where(*conditions))
        return int(result.rowcount or 0)

    @staticmethod
    def _assert_writable(identity: LearnerIdentity) -> None:
        if identity.memory_write_blocked:
            raise MemoryControlError("Memory writes are blocked by a deletion job")
