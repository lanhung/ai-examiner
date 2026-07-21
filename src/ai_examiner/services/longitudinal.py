from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Concept,
    KnowledgeUnit,
    KnowledgeUnitConceptMap,
    LearnerConceptState,
    LearnerIdentity,
    LearnerMemoryEvent,
    RetestItem,
    RetestPlan,
)

ALGORITHMS = frozenset(
    {"no-decay-v1", "fixed-half-life-v1", "evidence-half-life-v1"}
)
ASSISTANCE_MULTIPLIERS = {
    "direct": 1.0,
    "followup": 0.65,
    "hint": 0.45,
    "corrected": 0.25,
}
TARGET_RETENTION = 0.70
STATE_EVENT_TYPES = frozenset(
    {"concept_evidence", "concept_correction", "retest_outcome"}
)


class LongitudinalStateError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class LongitudinalStateService:
    state_version = "longitudinal-state-v1"
    retest_policy_version = "retest-shadow-v1"

    def __init__(self, db: Session):
        self.db = db

    def rebuild(
        self,
        identity: LearnerIdentity,
        *,
        algorithm_version: str,
        dry_run: bool,
        as_of: datetime | None = None,
    ) -> list[dict]:
        self._validate_algorithm(algorithm_version)
        calculation_time = ensure_utc(as_of or utcnow())
        events = self.db.scalars(
            select(LearnerMemoryEvent)
            .where(
                LearnerMemoryEvent.learner_identity_id == identity.id,
                LearnerMemoryEvent.event_type.in_(STATE_EVENT_TYPES),
                LearnerMemoryEvent.concept_id.is_not(None),
                LearnerMemoryEvent.deleted_at.is_(None),
            )
            .order_by(LearnerMemoryEvent.occurred_at, LearnerMemoryEvent.id)
        ).all()
        superseded = {
            event.supersedes_event_id for event in events if event.supersedes_event_id
        }
        grouped: dict[str, list[LearnerMemoryEvent]] = defaultdict(list)
        for event in events:
            if event.id in superseded:
                continue
            if event.concept_id:
                grouped[event.concept_id].append(event)

        calculated = [
            self._calculate_concept(
                concept_id,
                concept_events,
                algorithm_version=algorithm_version,
                as_of=calculation_time,
            )
            for concept_id, concept_events in sorted(grouped.items())
        ]
        if dry_run:
            return calculated

        existing = {
            state.concept_id: state
            for state in self.db.scalars(
                select(LearnerConceptState).where(
                    LearnerConceptState.learner_identity_id == identity.id
                )
            ).all()
        }
        active_concepts = {item["concept_id"] for item in calculated}
        for concept_id, state in existing.items():
            if concept_id not in active_concepts:
                self.db.delete(state)
        for item in calculated:
            state = existing.get(item["concept_id"])
            if not state:
                state = LearnerConceptState(
                    learner_identity_id=identity.id,
                    concept_id=item["concept_id"],
                    last_observed_at=item["last_observed_at"],
                )
                self.db.add(state)
            for field in (
                "observed_mastery",
                "observed_confidence",
                "last_observed_at",
                "predicted_retention",
                "prediction_confidence",
                "stability_days",
                "difficulty_estimate",
                "evidence_count",
                "independent_evidence_count",
                "assisted_evidence_count",
                "active_misconceptions",
                "next_retest_at",
                "algorithm_version",
            ):
                setattr(state, field, item[field])
            state.rebuilt_at = calculation_time
        self.db.flush()
        return calculated

    def states(
        self, identity: LearnerIdentity, *, as_of: datetime | None = None
    ) -> list[dict]:
        calculation_time = ensure_utc(as_of or utcnow())
        states = self.db.scalars(
            select(LearnerConceptState)
            .where(LearnerConceptState.learner_identity_id == identity.id)
            .order_by(LearnerConceptState.next_retest_at, LearnerConceptState.concept_id)
        ).all()
        concepts = self._concepts({state.concept_id for state in states})
        return [
            self._serialize_state(state, concepts.get(state.concept_id), calculation_time)
            for state in states
        ]

    def growth(
        self,
        identity: LearnerIdentity,
        *,
        concept_id: str | None = None,
        algorithm_version: str = "evidence-half-life-v1",
    ) -> list[dict]:
        self._validate_algorithm(algorithm_version)
        query = select(LearnerMemoryEvent).where(
            LearnerMemoryEvent.learner_identity_id == identity.id,
            LearnerMemoryEvent.event_type.in_(STATE_EVENT_TYPES),
            LearnerMemoryEvent.concept_id.is_not(None),
            LearnerMemoryEvent.deleted_at.is_(None),
        )
        if concept_id:
            query = query.where(LearnerMemoryEvent.concept_id == concept_id)
        events = self.db.scalars(
            query.order_by(LearnerMemoryEvent.occurred_at, LearnerMemoryEvent.id)
        ).all()
        superseded = {
            event.supersedes_event_id for event in events if event.supersedes_event_id
        }
        grouped: dict[str, list[LearnerMemoryEvent]] = defaultdict(list)
        for event in events:
            if event.id in superseded:
                continue
            if event.concept_id:
                grouped[event.concept_id].append(event)
        concepts = self._concepts(set(grouped))
        series = []
        for current_concept_id, concept_events in sorted(grouped.items()):
            points = []
            for index, event in enumerate(concept_events, start=1):
                snapshot = self._calculate_concept(
                    current_concept_id,
                    concept_events[:index],
                    algorithm_version=algorithm_version,
                    as_of=ensure_utc(event.occurred_at),
                )
                points.append(
                    {
                        "memory_event_id": event.id,
                        "observed_at": ensure_utc(event.occurred_at).isoformat(),
                        "observed_mastery": snapshot["observed_mastery"],
                        "observed_confidence": snapshot["observed_confidence"],
                        "independent_evidence_count": snapshot[
                            "independent_evidence_count"
                        ],
                        "assisted_evidence_count": snapshot["assisted_evidence_count"],
                    }
                )
            concept = concepts.get(current_concept_id)
            series.append(
                {
                    "concept_id": current_concept_id,
                    "concept_title": concept.title if concept else None,
                    "algorithm_version": algorithm_version,
                    "points": points,
                }
            )
        return series

    def create_retest_plan(
        self,
        identity: LearnerIdentity,
        *,
        horizon_days: int,
        max_items: int,
        mode: str,
        as_of: datetime | None = None,
    ) -> dict:
        if mode != "shadow":
            raise LongitudinalStateError("Only shadow retest plans are enabled in v0.7")
        if not identity.memory_enabled:
            raise LongitudinalStateError("Long-term memory is disabled for this identity")
        if not identity.retest_planning_enabled:
            raise LongitudinalStateError("Retest planning is disabled for this identity")
        calculation_time = ensure_utc(as_of or utcnow())
        horizon_end = calculation_time + timedelta(days=horizon_days)
        states = self.db.scalars(
            select(LearnerConceptState).where(
                LearnerConceptState.learner_identity_id == identity.id
            )
        ).all()
        if not states:
            raise LongitudinalStateError("Rebuild longitudinal state before planning retests")
        dismissed_concepts = set(
            self.db.scalars(
                select(RetestItem.concept_id)
                .join(RetestPlan, RetestPlan.id == RetestItem.retest_plan_id)
                .where(
                    RetestPlan.learner_identity_id == identity.id,
                    RetestItem.status == "dismissed",
                    RetestItem.dismissed_until.is_not(None),
                    RetestItem.dismissed_until > calculation_time,
                )
            ).all()
        )
        importance = self._concept_importance({state.concept_id for state in states})
        candidates = []
        for state in states:
            if state.concept_id in dismissed_concepts:
                continue
            current = self._serialize_state(state, None, calculation_time)
            due_at = ensure_utc(state.next_retest_at or calculation_time)
            has_misconception = bool(state.active_misconceptions)
            if due_at > horizon_end and not has_misconception:
                continue
            retention_gap = max(0.0, TARGET_RETENTION - current["predicted_retention"])
            uncertainty = 1.0 - current["prediction_confidence"]
            overdue_days = max(0.0, (calculation_time - due_at).total_seconds() / 86400)
            elapsed_days = max(
                0.0,
                (calculation_time - ensure_utc(state.last_observed_at)).total_seconds()
                / 86400,
            )
            recent_penalty = 0.20 if elapsed_days < 1.0 and not has_misconception else 0.0
            independent_recall_gap = (
                0.10 if state.independent_evidence_count == 0 else 0.0
            )
            priority = clamp(
                (retention_gap / TARGET_RETENTION) * 0.35
                + uncertainty * 0.20
                + (0.25 if has_misconception else 0.0)
                + importance.get(state.concept_id, 0.7) * 0.10
                + min(0.15, overdue_days / 30 * 0.15)
                - recent_penalty
                + independent_recall_gap
            )
            reason_code = (
                "unresolved_misconception"
                if has_misconception
                else "retention_below_target"
                if current["predicted_retention"] < TARGET_RETENTION
                else "high_uncertainty"
                if uncertainty >= 0.5
                else "scheduled_review"
            )
            candidates.append(
                {
                    "state": state,
                    "due_at": due_at,
                    "priority": round(priority, 6),
                    "reason_code": reason_code,
                    "predicted_retention": current["predicted_retention"],
                    "uncertainty": round(uncertainty, 6),
                }
            )
        candidates.sort(
            key=lambda item: (-item["priority"], item["due_at"], item["state"].concept_id)
        )
        plan = RetestPlan(
            learner_identity_id=identity.id,
            horizon_start=calculation_time,
            horizon_end=horizon_end,
            status="shadow",
            policy_version=self.retest_policy_version,
        )
        self.db.add(plan)
        self.db.flush()
        for candidate in candidates[:max_items]:
            state = candidate["state"]
            self.db.add(
                RetestItem(
                    retest_plan_id=plan.id,
                    concept_id=state.concept_id,
                    due_at=candidate["due_at"],
                    priority=candidate["priority"],
                    reason_code=candidate["reason_code"],
                    predicted_retention=candidate["predicted_retention"],
                    uncertainty=candidate["uncertainty"],
                    source_state_version=(
                        f"{self.state_version}:{state.algorithm_version}"
                    ),
                    status="proposed",
                )
            )
        self.db.flush()
        return self.serialize_plan(plan)

    def plans(self, identity: LearnerIdentity) -> list[dict]:
        plans = self.db.scalars(
            select(RetestPlan)
            .where(RetestPlan.learner_identity_id == identity.id)
            .order_by(RetestPlan.created_at.desc(), RetestPlan.id.desc())
        ).all()
        return [self.serialize_plan(plan) for plan in plans]

    def serialize_plan(self, plan: RetestPlan) -> dict:
        items = self.db.scalars(
            select(RetestItem)
            .where(RetestItem.retest_plan_id == plan.id)
            .order_by(RetestItem.priority.desc(), RetestItem.due_at, RetestItem.id)
        ).all()
        concepts = self._concepts({item.concept_id for item in items})
        return {
            "id": plan.id,
            "learner_identity_id": plan.learner_identity_id,
            "horizon_start": ensure_utc(plan.horizon_start).isoformat(),
            "horizon_end": ensure_utc(plan.horizon_end).isoformat(),
            "status": plan.status,
            "policy_version": plan.policy_version,
            "created_at": ensure_utc(plan.created_at).isoformat(),
            "items": [
                {
                    "id": item.id,
                    "concept_id": item.concept_id,
                    "concept_title": concepts[item.concept_id].title
                    if item.concept_id in concepts
                    else None,
                    "due_at": ensure_utc(item.due_at).isoformat(),
                    "priority": item.priority,
                    "reason_code": item.reason_code,
                    "predicted_retention": item.predicted_retention,
                    "uncertainty": item.uncertainty,
                    "source_state_version": item.source_state_version,
                    "selected_question_id": item.selected_question_id,
                    "outcome_event_id": item.outcome_event_id,
                    "status": item.status,
                    "exam_session_id": item.exam_session_id,
                    "dismissed_until": ensure_utc(item.dismissed_until).isoformat()
                    if item.dismissed_until
                    else None,
                    "accepted_at": ensure_utc(item.accepted_at).isoformat()
                    if item.accepted_at
                    else None,
                    "started_at": ensure_utc(item.started_at).isoformat()
                    if item.started_at
                    else None,
                    "completed_at": ensure_utc(item.completed_at).isoformat()
                    if item.completed_at
                    else None,
                }
                for item in items
            ],
        }

    def _calculate_concept(
        self,
        concept_id: str,
        events: list[LearnerMemoryEvent],
        *,
        algorithm_version: str,
        as_of: datetime,
    ) -> dict:
        samples = []
        independent_count = 0
        active_misconceptions: list[str] = []
        for event in events:
            payload = event.payload_json or {}
            assistance = str(payload.get("assistance_level") or "direct")
            multiplier = ASSISTANCE_MULTIPLIERS.get(assistance, 0.5)
            weight = max(0.01, safe_float(payload.get("evidence_weight"), 1.0)) * multiplier
            observation = clamp(safe_float(payload.get("observation"), 0.0))
            samples.append((observation, weight))
            if assistance == "direct":
                independent_count += 1
            for misconception in payload.get("detected_misconceptions") or []:
                normalized = str(misconception).strip()
                if normalized and normalized not in active_misconceptions:
                    active_misconceptions.append(normalized)
            for resolved in payload.get("resolved_misconceptions") or []:
                normalized = str(resolved).strip()
                if normalized in active_misconceptions:
                    active_misconceptions.remove(normalized)
        total_weight = sum(weight for _, weight in samples)
        observed = sum(value * weight for value, weight in samples) / total_weight
        variance = sum(weight * (value - observed) ** 2 for value, weight in samples) / total_weight
        evidence_confidence = total_weight / (total_weight + 2.0)
        consistency = 1.0 - min(0.5, math.sqrt(max(0.0, variance)))
        observed_confidence = clamp(evidence_confidence * consistency, high=0.95)
        last_observed = max(ensure_utc(event.occurred_at) for event in events)
        assisted_count = len(events) - independent_count
        stability = self._stability_days(
            algorithm_version,
            observed_mastery=observed,
            independent_count=independent_count,
        )
        elapsed_days = max(0.0, (as_of - last_observed).total_seconds() / 86400)
        predicted = self._predict_retention(
            observed, elapsed_days=elapsed_days, stability_days=stability,
            algorithm_version=algorithm_version,
        )
        prediction_confidence = clamp(
            observed_confidence * math.exp(-elapsed_days / max(1.0, stability * 2.0))
        )
        next_retest = self._next_retest_at(
            observed, last_observed=last_observed, stability_days=stability,
            algorithm_version=algorithm_version,
        )
        return {
            "concept_id": concept_id,
            "observed_mastery": round(observed, 6),
            "observed_confidence": round(observed_confidence, 6),
            "last_observed_at": last_observed,
            "predicted_retention": round(predicted, 6),
            "prediction_confidence": round(prediction_confidence, 6),
            "stability_days": round(stability, 6),
            "difficulty_estimate": round(1.0 + 9.0 * (1.0 - observed), 6),
            "evidence_count": len(events),
            "independent_evidence_count": independent_count,
            "assisted_evidence_count": assisted_count,
            "active_misconceptions": active_misconceptions,
            "next_retest_at": next_retest,
            "algorithm_version": algorithm_version,
            "rebuilt_at": as_of,
        }

    def _serialize_state(
        self, state: LearnerConceptState, concept: Concept | None, as_of: datetime
    ) -> dict:
        elapsed_days = max(
            0.0,
            (as_of - ensure_utc(state.last_observed_at)).total_seconds() / 86400,
        )
        predicted = self._predict_retention(
            state.observed_mastery,
            elapsed_days=elapsed_days,
            stability_days=state.stability_days,
            algorithm_version=state.algorithm_version,
        )
        prediction_confidence = clamp(
            state.observed_confidence
            * math.exp(-elapsed_days / max(1.0, state.stability_days * 2.0))
        )
        return {
            "id": state.id,
            "concept_id": state.concept_id,
            "concept_title": concept.title if concept else None,
            "observed_mastery": state.observed_mastery,
            "observed_confidence": state.observed_confidence,
            "last_observed_at": ensure_utc(state.last_observed_at).isoformat(),
            "predicted_retention": round(predicted, 6),
            "prediction_confidence": round(prediction_confidence, 6),
            "predicted_at": as_of.isoformat(),
            "stability_days": state.stability_days,
            "difficulty_estimate": state.difficulty_estimate,
            "evidence_count": state.evidence_count,
            "independent_evidence_count": state.independent_evidence_count,
            "assisted_evidence_count": state.assisted_evidence_count,
            "active_misconceptions": state.active_misconceptions,
            "next_retest_at": ensure_utc(state.next_retest_at).isoformat()
            if state.next_retest_at
            else None,
            "algorithm_version": state.algorithm_version,
            "rebuilt_at": ensure_utc(state.rebuilt_at).isoformat(),
        }

    @staticmethod
    def _stability_days(
        algorithm_version: str, *, observed_mastery: float, independent_count: int
    ) -> float:
        if algorithm_version == "no-decay-v1":
            return 36500.0
        if algorithm_version == "fixed-half-life-v1":
            return 30.0
        return clamp(
            14.0 * (1.0 + 0.6 * independent_count) * (0.75 + observed_mastery),
            low=7.0,
            high=365.0,
        )

    @staticmethod
    def _predict_retention(
        observed_mastery: float,
        *,
        elapsed_days: float,
        stability_days: float,
        algorithm_version: str,
    ) -> float:
        if algorithm_version == "no-decay-v1":
            return clamp(observed_mastery)
        return clamp(observed_mastery * 0.5 ** (elapsed_days / max(1.0, stability_days)))

    @staticmethod
    def _next_retest_at(
        observed_mastery: float,
        *,
        last_observed: datetime,
        stability_days: float,
        algorithm_version: str,
    ) -> datetime:
        if observed_mastery <= TARGET_RETENTION:
            return last_observed
        if algorithm_version == "no-decay-v1":
            return last_observed + timedelta(days=365)
        days = stability_days * math.log(TARGET_RETENTION / observed_mastery, 0.5)
        return last_observed + timedelta(days=max(0.0, days))

    def _concepts(self, concept_ids: set[str]) -> dict[str, Concept]:
        if not concept_ids:
            return {}
        return {
            concept.id: concept
            for concept in self.db.scalars(
                select(Concept).where(Concept.id.in_(concept_ids))
            ).all()
        }

    def _concept_importance(self, concept_ids: set[str]) -> dict[str, float]:
        if not concept_ids:
            return {}
        rows = self.db.execute(
            select(KnowledgeUnitConceptMap.concept_id, KnowledgeUnit.importance)
            .join(
                KnowledgeUnit,
                KnowledgeUnit.id == KnowledgeUnitConceptMap.knowledge_unit_id,
            )
            .where(
                KnowledgeUnitConceptMap.concept_id.in_(concept_ids),
                KnowledgeUnitConceptMap.status == "accepted",
            )
        ).all()
        grouped: dict[str, list[float]] = defaultdict(list)
        for concept_id, importance in rows:
            grouped[concept_id].append(clamp(float(importance)))
        return {
            concept_id: sum(values) / len(values) for concept_id, values in grouped.items()
        }

    @staticmethod
    def _validate_algorithm(algorithm_version: str) -> None:
        if algorithm_version not in ALGORITHMS:
            raise LongitudinalStateError(
                f"Unsupported longitudinal algorithm: {algorithm_version}"
            )
