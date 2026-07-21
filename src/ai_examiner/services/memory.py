from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Concept,
    KnowledgeEvidenceEvent,
    KnowledgeUnitConceptMap,
    LearnerIdentity,
    LearnerIdentityLink,
    LearnerMemoryEvent,
    LearnerSubject,
)

ALLOWED_MEMORY_CATEGORIES = frozenset(
    {
        "concept_evidence",
        "misconception",
        "retest_outcome",
        "explicit_preference",
        "confirmed_preference",
        "concept_mapping",
        "memory_control",
    }
)
LONGITUDINAL_RELATIONS = frozenset({"exact", "narrower"})


class MemoryPolicyError(ValueError):
    pass


class MemoryConflictError(MemoryPolicyError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_external_reference(secret: str, external_reference: str) -> str:
    normalized = external_reference.strip()
    if not secret:
        raise MemoryPolicyError("MEMORY_IDENTITY_SECRET is not configured")
    if not normalized:
        raise MemoryPolicyError("External subject reference cannot be empty")
    return hmac.new(
        secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def canonical_token(value: str) -> str:
    token = re.sub(r"[^\w.-]+", "-", value.strip().casefold()).strip("-_.")
    if not token:
        raise MemoryPolicyError("Canonical key must contain letters or digits")
    return token


class LearnerMemoryService:
    policy_version = "memory-policy-v1"
    ledger_version = "memory-ledger-v1"

    def __init__(self, db: Session, identity_secret: str | None):
        self.db = db
        self.identity_secret = identity_secret or ""

    def create_identity(
        self,
        *,
        external_subject_ref: str,
        display_name: str | None,
        memory_enabled: bool,
        memory_scope: str,
    ) -> tuple[LearnerIdentity, bool]:
        key_hash = hash_external_reference(self.identity_secret, external_subject_ref)
        existing = self.db.scalar(
            select(LearnerIdentity).where(LearnerIdentity.opaque_key_hash == key_hash)
        )
        if existing:
            return existing, False
        identity = LearnerIdentity(
            opaque_key_hash=key_hash,
            display_name=display_name.strip() if display_name else None,
            memory_enabled=memory_enabled,
            memory_scope=memory_scope,
            policy_version=self.policy_version,
        )
        self.db.add(identity)
        self.db.flush()
        return identity, True

    def update_settings(self, identity: LearnerIdentity, values: dict) -> LearnerIdentity:
        if "memory_enabled" in values:
            identity.memory_enabled = bool(values["memory_enabled"])
            identity.disabled_at = None if identity.memory_enabled else utcnow()
        for field in (
            "memory_scope",
            "preference_inference_enabled",
            "retest_planning_enabled",
            "retention_days",
        ):
            if field in values:
                setattr(identity, field, values[field])
        identity.policy_version = self.policy_version
        self._append_control_event(identity, "memory_settings_updated", values)
        self.db.flush()
        return identity

    def link_subject(
        self,
        identity: LearnerIdentity,
        subject: LearnerSubject,
        *,
        provenance: str,
    ) -> tuple[LearnerIdentityLink, bool]:
        if identity.memory_scope == "project_only":
            linked_projects = set(
                self.db.scalars(
                    select(LearnerSubject.project_id)
                    .join(
                        LearnerIdentityLink,
                        LearnerIdentityLink.learner_subject_id == LearnerSubject.id,
                    )
                    .where(
                        LearnerIdentityLink.learner_identity_id == identity.id,
                        LearnerIdentityLink.status == "confirmed",
                    )
                ).all()
            )
            if linked_projects and subject.project_id not in linked_projects:
                raise MemoryConflictError(
                    "Identity memory scope is project_only; enable linked_projects first"
                )
        existing = self.db.scalar(
            select(LearnerIdentityLink).where(
                LearnerIdentityLink.learner_subject_id == subject.id
            )
        )
        if existing:
            if existing.learner_identity_id != identity.id:
                raise MemoryConflictError(
                    "Learner subject is already bound to a different identity"
                )
            if existing.status == "confirmed":
                return existing, False
            existing.status = "confirmed"
            existing.provenance = provenance
            existing.revoked_at = None
            self.db.flush()
            return existing, False
        link = LearnerIdentityLink(
            learner_identity_id=identity.id,
            learner_subject_id=subject.id,
            status="confirmed",
            provenance=provenance,
        )
        self.db.add(link)
        self.db.flush()
        return link, True

    def revoke_link(self, identity: LearnerIdentity, link: LearnerIdentityLink) -> None:
        if link.learner_identity_id != identity.id:
            raise MemoryConflictError("Identity link does not belong to this identity")
        link.status = "revoked"
        link.revoked_at = utcnow()
        self.db.flush()

    def create_concept(
        self,
        *,
        namespace: str,
        canonical_key: str,
        title: str,
        description: str,
        language: str,
    ) -> tuple[Concept, bool]:
        normalized_namespace = canonical_token(namespace)
        normalized_key = canonical_token(canonical_key)
        existing = self.db.scalar(
            select(Concept).where(
                Concept.namespace == normalized_namespace,
                Concept.canonical_key == normalized_key,
            )
        )
        if existing:
            return existing, False
        concept = Concept(
            namespace=normalized_namespace,
            canonical_key=normalized_key,
            title=title.strip(),
            description=description.strip(),
            language=language,
        )
        self.db.add(concept)
        self.db.flush()
        return concept, True

    def create_mapping(
        self,
        *,
        knowledge_unit_id: str,
        concept_id: str,
        relation: str,
        confidence: float,
        source: str,
        evidence: dict,
        model_profile: str | None,
        prompt_version: str | None,
    ) -> tuple[KnowledgeUnitConceptMap, bool]:
        existing = self.db.scalar(
            select(KnowledgeUnitConceptMap).where(
                KnowledgeUnitConceptMap.knowledge_unit_id == knowledge_unit_id,
                KnowledgeUnitConceptMap.concept_id == concept_id,
            )
        )
        if existing:
            return existing, False
        mapping = KnowledgeUnitConceptMap(
            knowledge_unit_id=knowledge_unit_id,
            concept_id=concept_id,
            relation=relation,
            confidence=confidence,
            status="proposed",
            source=source,
            evidence_json=evidence,
            model_profile=model_profile,
            prompt_version=prompt_version,
        )
        self.db.add(mapping)
        self.db.flush()
        return mapping, True

    def review_mapping(
        self, mapping: KnowledgeUnitConceptMap, status: str
    ) -> KnowledgeUnitConceptMap:
        if status not in {"accepted", "rejected"}:
            raise MemoryPolicyError("Mapping status must be accepted or rejected")
        mapping.status = status
        mapping.reviewed_at = utcnow()
        self.db.flush()
        return mapping

    def import_evidence(self, identity: LearnerIdentity, *, dry_run: bool) -> dict:
        if not identity.memory_enabled:
            raise MemoryConflictError("Long-term memory is disabled for this identity")
        subject_ids = list(
            self.db.scalars(
                select(LearnerIdentityLink.learner_subject_id).where(
                    LearnerIdentityLink.learner_identity_id == identity.id,
                    LearnerIdentityLink.status == "confirmed",
                )
            ).all()
        )
        if not subject_ids:
            return {"eligible": 0, "imported": 0, "skipped": 0, "dry_run": dry_run}

        rows = self.db.execute(
            select(KnowledgeEvidenceEvent, KnowledgeUnitConceptMap)
            .join(
                KnowledgeUnitConceptMap,
                KnowledgeUnitConceptMap.knowledge_unit_id
                == KnowledgeEvidenceEvent.knowledge_unit_id,
            )
            .where(
                KnowledgeEvidenceEvent.learner_subject_id.in_(subject_ids),
                KnowledgeUnitConceptMap.status == "accepted",
                KnowledgeUnitConceptMap.relation.in_(LONGITUDINAL_RELATIONS),
            )
            .order_by(KnowledgeEvidenceEvent.created_at, KnowledgeEvidenceEvent.id)
        ).all()
        existing = {
            (event.source_evidence_event_id, event.concept_id, event.event_type)
            for event in self.db.scalars(
                select(LearnerMemoryEvent).where(
                    LearnerMemoryEvent.learner_identity_id == identity.id,
                    LearnerMemoryEvent.source_evidence_event_id.is_not(None),
                )
            ).all()
        }
        imported = 0
        skipped = 0
        for evidence, mapping in rows:
            key = (evidence.id, mapping.concept_id, "concept_evidence")
            if key in existing:
                skipped += 1
                continue
            self._validate_category("concept_evidence")
            if not dry_run:
                self.db.add(
                    LearnerMemoryEvent(
                        learner_identity_id=identity.id,
                        learner_subject_id=evidence.learner_subject_id,
                        concept_id=mapping.concept_id,
                        source_evidence_event_id=evidence.id,
                        event_type="concept_evidence",
                        payload_json={
                            "observation": evidence.observation,
                            "evidence_weight": evidence.evidence_weight,
                            "correctness": evidence.correctness,
                            "coverage": evidence.coverage,
                            "evidence_reasoning": evidence.evidence_reasoning,
                            "analyzer_confidence": evidence.analyzer_confidence,
                            "assistance_level": evidence.assistance_level,
                            "detected_misconceptions": evidence.detected_misconceptions,
                            "resolved_misconceptions": evidence.resolved_misconceptions,
                            "source_type": evidence.source_type,
                            "source_algorithm_version": evidence.algorithm_version,
                            "mapping_id": mapping.id,
                            "mapping_relation": mapping.relation,
                        },
                        occurred_at=evidence.created_at,
                        policy_version=self.policy_version,
                        algorithm_version=self.ledger_version,
                    )
                )
            existing.add(key)
            imported += 1
        if not dry_run:
            self.db.flush()
        return {
            "eligible": len(rows),
            "imported": imported,
            "skipped": skipped,
            "dry_run": dry_run,
        }

    def _append_control_event(
        self, identity: LearnerIdentity, action: str, values: dict
    ) -> None:
        self._validate_category("memory_control")
        safe_values = {
            key: value
            for key, value in values.items()
            if key
            in {
                "memory_enabled",
                "memory_scope",
                "preference_inference_enabled",
                "retest_planning_enabled",
                "retention_days",
            }
        }
        self.db.add(
            LearnerMemoryEvent(
                learner_identity_id=identity.id,
                learner_subject_id=None,
                event_type="memory_control",
                payload_json={"action": action, "settings": safe_values},
                occurred_at=utcnow(),
                policy_version=self.policy_version,
                algorithm_version=self.ledger_version,
            )
        )

    @staticmethod
    def _validate_category(category: str) -> None:
        if category not in ALLOWED_MEMORY_CATEGORIES:
            raise MemoryPolicyError(f"Memory category is not allowed: {category}")
