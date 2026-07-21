from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Blueprint,
    ExamSession,
    KnowledgeEvidenceEvent,
    KnowledgeUnit,
    KnowledgeUnitConceptMap,
    LearnerConceptState,
    LearnerIdentity,
    LearnerIdentityLink,
    LearnerMemoryEvent,
    LearnerSubject,
    QuestionKnowledgeUnit,
    RetestItem,
    RetestPlan,
    Turn,
)
from .cognitive import CognitiveStateService
from .longitudinal import LongitudinalStateService


class RetestLifecycleError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class RetestLifecycleService:
    policy_version = "retest-user-started-v1"

    def __init__(self, db: Session):
        self.db = db

    def item_for_identity(
        self, identity: LearnerIdentity, item_id: str
    ) -> RetestItem:
        item = self.db.scalar(
            select(RetestItem)
            .join(RetestPlan, RetestPlan.id == RetestItem.retest_plan_id)
            .where(
                RetestItem.id == item_id,
                RetestPlan.learner_identity_id == identity.id,
            )
        )
        if not item:
            raise RetestLifecycleError("Retest item not found")
        return item

    def act(
        self,
        identity: LearnerIdentity,
        item: RetestItem,
        *,
        action: str,
        cooldown_days: int,
    ) -> RetestItem:
        self._assert_writable(identity)
        now = utcnow()
        if action == "accept":
            if item.status not in {"proposed", "dismissed"}:
                raise RetestLifecycleError("Only proposed or dismissed items can be accepted")
            item.status = "accepted"
            item.accepted_at = now
            item.dismissed_until = None
        elif action == "dismiss":
            if item.status not in {"proposed", "accepted"}:
                raise RetestLifecycleError("Only proposed or accepted items can be dismissed")
            item.status = "dismissed"
            item.dismissed_until = now + timedelta(days=cooldown_days)
        else:
            raise RetestLifecycleError("Unsupported retest action")
        self.db.flush()
        return item

    def start_session(
        self,
        identity: LearnerIdentity,
        item: RetestItem,
        *,
        blueprint: Blueprint,
        profile: str,
    ) -> ExamSession:
        self._assert_writable(identity)
        if item.status != "accepted":
            raise RetestLifecycleError("Accept the retest recommendation before starting")
        if item.exam_session_id:
            raise RetestLifecycleError("Retest item already has a session")
        CognitiveStateService(self.db).ensure_blueprint_graph(blueprint)
        question_id = self._select_question(identity, item, blueprint)
        subject = self.db.scalar(
            select(LearnerSubject)
            .join(
                LearnerIdentityLink,
                LearnerIdentityLink.learner_subject_id == LearnerSubject.id,
            )
            .where(
                LearnerIdentityLink.learner_identity_id == identity.id,
                LearnerIdentityLink.status == "confirmed",
                LearnerSubject.project_id == blueprint.project_id,
            )
        )
        if not subject:
            raise RetestLifecycleError(
                "Link this identity to a learner subject in the selected project"
            )
        session = ExamSession(
            project_id=blueprint.project_id,
            blueprint_id=blueprint.id,
            mode="retest",
            config={
                "profile": profile,
                "question_limit": 1,
                "max_followups_per_question": 0,
                "allow_hints": False,
                "allow_corrections": False,
                "allow_interruptions": False,
                "target_question_id": question_id,
                "retest_item_id": item.id,
            },
            learner_subject_id=subject.id,
            question_strategy="fixed",
            policy_version=self.policy_version,
        )
        self.db.add(session)
        self.db.flush()
        item.status = "started"
        item.selected_question_id = question_id
        item.exam_session_id = session.id
        item.started_at = utcnow()
        self.db.flush()
        return session

    def complete_from_session(
        self,
        session: ExamSession,
        user_turn: Turn,
    ) -> RetestItem | None:
        item_id = str((session.config or {}).get("retest_item_id") or "")
        if not item_id or session.status != "completed":
            return None
        item = self.db.get(RetestItem, item_id)
        if not item or item.status != "started" or item.exam_session_id != session.id:
            return None
        plan = self.db.get(RetestPlan, item.retest_plan_id)
        if not plan:
            return None
        evaluation = user_turn.evaluation or {}
        analysis = user_turn.analysis or {}
        event = LearnerMemoryEvent(
            learner_identity_id=plan.learner_identity_id,
            learner_subject_id=session.learner_subject_id,
            concept_id=item.concept_id,
            event_type="retest_outcome",
            payload_json={
                "observation": max(0.0, min(1.0, float(evaluation.get("score", 0)) / 5)),
                "evidence_weight": 1.0,
                "assistance_level": "direct",
                "correctness": analysis.get("correctness", "unknown"),
                "coverage": analysis.get("coverage", 0.0),
                "detected_misconceptions": analysis.get("errors", []),
                "resolved_misconceptions": [],
                "source_type": "retest",
                "retest_item_id": item.id,
                "question_id": item.selected_question_id,
            },
            occurred_at=user_turn.created_at,
            policy_version=self.policy_version,
            algorithm_version="retest-outcome-v1",
        )
        self.db.add(event)
        self.db.flush()
        item.outcome_event_id = event.id
        item.status = "completed"
        item.completed_at = utcnow()
        identity = self.db.get(LearnerIdentity, plan.learner_identity_id)
        if identity:
            algorithm = self.db.scalar(
                select(LearnerConceptState.algorithm_version).where(
                    LearnerConceptState.learner_identity_id == identity.id
                )
            ) or "evidence-half-life-v1"
            LongitudinalStateService(self.db).rebuild(
                identity, algorithm_version=algorithm, dry_run=False
            )
        self.db.flush()
        return item

    def _select_question(
        self, identity: LearnerIdentity, item: RetestItem, blueprint: Blueprint
    ) -> str:
        rows = self.db.execute(
            select(QuestionKnowledgeUnit.question_id, QuestionKnowledgeUnit.is_primary)
            .join(
                KnowledgeUnit,
                KnowledgeUnit.id == QuestionKnowledgeUnit.knowledge_unit_id,
            )
            .join(
                KnowledgeUnitConceptMap,
                KnowledgeUnitConceptMap.knowledge_unit_id == KnowledgeUnit.id,
            )
            .where(
                QuestionKnowledgeUnit.blueprint_id == blueprint.id,
                KnowledgeUnitConceptMap.concept_id == item.concept_id,
                KnowledgeUnitConceptMap.status == "accepted",
                KnowledgeUnitConceptMap.relation.in_(["exact", "narrower"]),
            )
            .order_by(QuestionKnowledgeUnit.is_primary.desc(), QuestionKnowledgeUnit.question_id)
        ).all()
        available = {str(question.get("id")) for question in blueprint.data.get("questions", [])}
        candidates = [question_id for question_id, _ in rows if question_id in available]
        if not candidates:
            raise RetestLifecycleError(
                "No accepted concept mapping connects this retest to the blueprint"
            )
        prior = set(
            self.db.scalars(
                select(KnowledgeEvidenceEvent.question_id)
                .join(
                    LearnerMemoryEvent,
                    LearnerMemoryEvent.source_evidence_event_id
                    == KnowledgeEvidenceEvent.id,
                )
                .where(
                    LearnerMemoryEvent.learner_identity_id == identity.id,
                    LearnerMemoryEvent.concept_id == item.concept_id,
                )
            ).all()
        )
        return next((candidate for candidate in candidates if candidate not in prior), candidates[0])

    @staticmethod
    def serialize_item(item: RetestItem) -> dict:
        return {
            "id": item.id,
            "status": item.status,
            "selected_question_id": item.selected_question_id,
            "exam_session_id": item.exam_session_id,
            "outcome_event_id": item.outcome_event_id,
            "dismissed_until": item.dismissed_until.isoformat()
            if item.dismissed_until
            else None,
            "accepted_at": item.accepted_at.isoformat() if item.accepted_at else None,
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "completed_at": item.completed_at.isoformat()
            if item.completed_at
            else None,
        }

    @staticmethod
    def _assert_writable(identity: LearnerIdentity) -> None:
        if not identity.memory_enabled:
            raise RetestLifecycleError("Long-term memory is disabled")
        if identity.memory_write_blocked:
            raise RetestLifecycleError("Memory writes are blocked by a deletion job")
