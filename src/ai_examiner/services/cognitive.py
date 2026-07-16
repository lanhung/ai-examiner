from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    AdaptiveDecision,
    Blueprint,
    ExamSession,
    KnowledgeEvidenceEvent,
    KnowledgeState,
    KnowledgeUnit,
    LearnerSubject,
    QuestionKnowledgeUnit,
    Turn,
)

IMPORTANCE_BY_TYPE = {
    "evidence": 0.95,
    "method": 0.90,
    "assumption": 0.90,
    "novelty": 0.85,
    "generalization": 0.82,
    "limitation": 0.78,
    "critical_reflection": 0.78,
    "motivation": 0.70,
}
ASSISTANCE_PENALTY = {"direct": 0.0, "followup": 0.10, "hint": 0.20, "correction": 0.30}
CORRECTNESS = {
    "supported": 1.0,
    "partially_supported": 0.65,
    "unsupported": 0.25,
    "insufficient": 0.10,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def concept_code(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return f"ku_{slug or hashlib.sha1(value.encode('utf-8')).hexdigest()[:12]}"


def misconception_code(value: str) -> str:
    return "mc_" + hashlib.sha1(value.strip().lower().encode("utf-8")).hexdigest()[:12]


class CognitiveStateService:
    algorithm_version = "knowledge-state-v1"

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_subject(self, project_id: str, subject_key: str | None) -> LearnerSubject | None:
        if not subject_key:
            return None
        normalized = subject_key.strip()
        if not normalized:
            return None
        subject = self.db.scalar(
            select(LearnerSubject).where(
                LearnerSubject.project_id == project_id,
                LearnerSubject.subject_key == normalized,
            )
        )
        if subject:
            return subject
        subject = LearnerSubject(project_id=project_id, subject_key=normalized)
        self.db.add(subject)
        self.db.flush()
        return subject

    def ensure_blueprint_graph(self, blueprint: Blueprint) -> None:
        questions = blueprint.data.get("questions", [])
        existing_units = {
            unit.code: unit
            for unit in self.db.scalars(
                select(KnowledgeUnit).where(KnowledgeUnit.blueprint_id == blueprint.id)
            ).all()
        }
        existing_mappings = {
            (mapping.question_id, mapping.knowledge_unit_id)
            for mapping in self.db.scalars(
                select(QuestionKnowledgeUnit).where(
                    QuestionKnowledgeUnit.blueprint_id == blueprint.id
                )
            ).all()
        }
        for question in questions:
            question_id = str(question.get("id", ""))
            if not question_id:
                continue
            raw_units = question.get("knowledge_units") or [
                {
                    "code": concept_code(str(question.get("type", "general"))),
                    "name": str(question.get("type", "general")).replace("_", " ").title(),
                    "description": f"Understanding demonstrated by {question.get('type', 'general')} questions",
                    "importance": IMPORTANCE_BY_TYPE.get(str(question.get("type")), 0.72),
                    "difficulty": int(question.get("difficulty", 3)),
                }
            ]
            for index, raw in enumerate(raw_units):
                if isinstance(raw, str):
                    raw = {"code": concept_code(raw), "name": raw}
                code = str(raw.get("code") or concept_code(str(raw.get("name", question.get("type", "general")))))
                unit = existing_units.get(code)
                if not unit:
                    unit = KnowledgeUnit(
                        project_id=blueprint.project_id,
                        blueprint_id=blueprint.id,
                        code=code,
                        name=str(raw.get("name") or code),
                        description=str(raw.get("description") or ""),
                        importance=clamp(float(raw.get("importance", 0.72))),
                        default_difficulty=max(
                            1, min(5, int(raw.get("difficulty", question.get("difficulty", 3))))
                        ),
                        prerequisite_codes=list(raw.get("prerequisite_codes") or []),
                        misconception_catalog=list(raw.get("misconception_catalog") or []),
                        source_evidence_asset_ids=list(
                            raw.get("source_evidence_asset_ids")
                            or question.get("evidence_asset_ids")
                            or []
                        ),
                    )
                    self.db.add(unit)
                    self.db.flush()
                    existing_units[code] = unit
                key = (question_id, unit.id)
                if key not in existing_mappings:
                    self.db.add(
                        QuestionKnowledgeUnit(
                            blueprint_id=blueprint.id,
                            question_id=question_id,
                            knowledge_unit_id=unit.id,
                            weight=clamp(float(raw.get("weight", 1.0 if index == 0 else 0.5))),
                            is_primary=index == 0,
                        )
                    )
                    existing_mappings.add(key)
        self.db.flush()

    def graph(self, blueprint_id: str) -> tuple[dict[str, dict], dict[str, list[dict]]]:
        units = {
            unit.id: self.serialize_unit(unit)
            for unit in self.db.scalars(
                select(KnowledgeUnit).where(KnowledgeUnit.blueprint_id == blueprint_id)
            ).all()
        }
        question_units: dict[str, list[dict]] = defaultdict(list)
        for mapping in self.db.scalars(
            select(QuestionKnowledgeUnit).where(
                QuestionKnowledgeUnit.blueprint_id == blueprint_id
            )
        ).all():
            question_units[mapping.question_id].append(
                {
                    "knowledge_unit_id": mapping.knowledge_unit_id,
                    "weight": mapping.weight,
                    "is_primary": mapping.is_primary,
                }
            )
        return units, dict(question_units)

    def states(self, session_id: str) -> dict[str, dict[str, Any]]:
        return {
            state.knowledge_unit_id: self.serialize_state(state)
            for state in self.db.scalars(
                select(KnowledgeState).where(KnowledgeState.session_id == session_id)
            ).all()
        }

    def evidence_for_session(self, session_id: str) -> dict[str, list[dict[str, Any]]]:
        events = self.db.scalars(
            select(KnowledgeEvidenceEvent)
            .where(KnowledgeEvidenceEvent.session_id == session_id)
            .order_by(KnowledgeEvidenceEvent.created_at, KnowledgeEvidenceEvent.id)
        ).all()
        turn_ids = {event.turn_id for event in events}
        turns = (
            {
                turn.id: turn
                for turn in self.db.scalars(select(Turn).where(Turn.id.in_(turn_ids))).all()
            }
            if turn_ids
            else {}
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            turn = turns.get(event.turn_id)
            grouped[event.knowledge_unit_id].append(
                {
                    "event_id": event.id,
                    "turn_id": event.turn_id,
                    "question_id": event.question_id,
                    "observation": round(event.observation, 6),
                    "evidence_weight": round(event.evidence_weight, 6),
                    "assistance_level": event.assistance_level,
                    "source_type": event.source_type,
                    "answer_quote": turn.content[:240] if turn else "",
                    "created_at": event.created_at.isoformat(),
                }
            )
        return dict(grouped)

    def effective_states(
        self, session: ExamSession, units: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Return current-session state enriched by the learner's cross-session evidence."""
        current = self.states(session.id)
        if not session.learner_subject_id:
            return current
        history = self._subject_aggregates(session.learner_subject_id)
        effective = {}
        for unit_id, unit in units.items():
            historical = history.get(str(unit.get("code")))
            if historical:
                effective[unit_id] = {
                    **historical,
                    "knowledge_unit_id": unit_id,
                    "source": "learner_history",
                }
            if unit_id in current:
                effective[unit_id] = {
                    **effective.get(unit_id, {}),
                    **current[unit_id],
                    "source": "current_session",
                }
        return effective

    def prior_question_ids(self, session: ExamSession) -> list[str]:
        if not session.learner_subject_id:
            return []
        return list(
            self.db.scalars(
                select(KnowledgeEvidenceEvent.question_id)
                .join(ExamSession, KnowledgeEvidenceEvent.session_id == ExamSession.id)
                .where(
                    KnowledgeEvidenceEvent.learner_subject_id == session.learner_subject_id,
                    KnowledgeEvidenceEvent.session_id != session.id,
                    ExamSession.blueprint_id == session.blueprint_id,
                )
                .distinct()
            ).all()
        )

    def record_answer(
        self,
        *,
        session: ExamSession,
        blueprint: Blueprint,
        turn: Turn,
        question: dict[str, Any],
        analysis: dict[str, Any],
        evaluation: dict[str, Any],
        assistance_level: str = "direct",
        source_type: str = "text",
    ) -> list[KnowledgeEvidenceEvent]:
        self.ensure_blueprint_graph(blueprint)
        units, question_units = self.graph(blueprint.id)
        mappings = question_units.get(str(question.get("id")), [])
        correctness = CORRECTNESS.get(str(analysis.get("correctness")), 0.10)
        coverage = clamp(float(analysis.get("coverage", 0.0)))
        evidence_reasoning = clamp(
            float((evaluation.get("dimensions") or {}).get("evidence_reasoning", 0.0)) / 5.0
        )
        analyzer_confidence = clamp(float(analysis.get("confidence", 0.5)))
        quality = 0.45 * correctness + 0.35 * coverage + 0.20 * evidence_reasoning
        observation = clamp(quality - ASSISTANCE_PENALTY.get(assistance_level, 0.10))
        errors = [str(item).strip() for item in analysis.get("errors", []) if str(item).strip()]
        events: list[KnowledgeEvidenceEvent] = []

        for mapping in mappings:
            unit_id = mapping["knowledge_unit_id"]
            existing = self.db.scalar(
                select(KnowledgeEvidenceEvent).where(
                    KnowledgeEvidenceEvent.turn_id == turn.id,
                    KnowledgeEvidenceEvent.knowledge_unit_id == unit_id,
                )
            )
            if existing:
                events.append(existing)
                continue
            weight = max(0.05, float(mapping.get("weight", 1.0)) * analyzer_confidence)
            state = self.db.scalar(
                select(KnowledgeState).where(
                    KnowledgeState.session_id == session.id,
                    KnowledgeState.knowledge_unit_id == unit_id,
                )
            )
            if not state:
                state = KnowledgeState(
                    session_id=session.id,
                    learner_subject_id=session.learner_subject_id,
                    knowledge_unit_id=unit_id,
                )
                self.db.add(state)
                self.db.flush()
            misconceptions, resolved = self._update_misconceptions(
                state.misconceptions or [], errors, observation, state.evidence_count + 1
            )
            event = KnowledgeEvidenceEvent(
                session_id=session.id,
                turn_id=turn.id,
                question_id=str(question.get("id")),
                knowledge_unit_id=unit_id,
                learner_subject_id=session.learner_subject_id,
                observation=observation,
                evidence_weight=weight,
                correctness=correctness,
                coverage=coverage,
                evidence_reasoning=evidence_reasoning,
                analyzer_confidence=analyzer_confidence,
                assistance_level=assistance_level,
                detected_misconceptions=errors,
                resolved_misconceptions=resolved,
                source_type=source_type,
                algorithm_version=self.algorithm_version,
            )
            self.db.add(event)
            self.db.flush()
            self._apply_observation(state, event, misconceptions)
            events.append(event)

        self._update_compatibility_snapshot(session, units)
        self.db.flush()
        return events

    def rebuild(self, session: ExamSession) -> list[dict[str, Any]]:
        events = self.db.scalars(
            select(KnowledgeEvidenceEvent)
            .where(KnowledgeEvidenceEvent.session_id == session.id)
            .order_by(KnowledgeEvidenceEvent.created_at, KnowledgeEvidenceEvent.id)
        ).all()
        self.db.execute(delete(KnowledgeState).where(KnowledgeState.session_id == session.id))
        self.db.flush()
        states: dict[str, KnowledgeState] = {}
        for event in events:
            state = states.get(event.knowledge_unit_id)
            if not state:
                state = KnowledgeState(
                    session_id=session.id,
                    learner_subject_id=session.learner_subject_id,
                    knowledge_unit_id=event.knowledge_unit_id,
                )
                self.db.add(state)
                self.db.flush()
                states[event.knowledge_unit_id] = state
            misconceptions, _ = self._update_misconceptions(
                state.misconceptions or [],
                event.detected_misconceptions or [],
                event.observation,
                state.evidence_count + 1,
            )
            self._apply_observation(state, event, misconceptions)
        units = {
            unit.id: self.serialize_unit(unit)
            for unit in self.db.scalars(
                select(KnowledgeUnit).where(KnowledgeUnit.blueprint_id == session.blueprint_id)
            ).all()
        }
        self._update_compatibility_snapshot(session, units)
        self.db.flush()
        return [self.serialize_state(state) for state in states.values()]

    def record_decision(
        self,
        *,
        session: ExamSession,
        action: str,
        selected_question_id: str | None,
        target_difficulty: int | None,
        reason_codes: list[str],
        candidate_scores: list[dict[str, Any]],
        policy_config: dict[str, Any] | None = None,
        turn_id: str | None = None,
    ) -> AdaptiveDecision:
        decision = AdaptiveDecision(
            session_id=session.id,
            turn_id=turn_id,
            strategy=session.question_strategy,
            action=action,
            selected_question_id=selected_question_id,
            target_difficulty=target_difficulty,
            reason_codes=reason_codes,
            candidate_scores=candidate_scores,
            policy_config=policy_config or {},
            policy_version=session.policy_version,
        )
        self.db.add(decision)
        self.db.flush()
        return decision

    def subject_summary(self, subject_id: str) -> list[dict[str, Any]]:
        return sorted(
            self._subject_aggregates(subject_id).values(),
            key=lambda item: (item["mastery"], item["code"]),
        )

    def _subject_aggregates(self, subject_id: str) -> dict[str, dict[str, Any]]:
        events = self.db.scalars(
            select(KnowledgeEvidenceEvent)
            .where(KnowledgeEvidenceEvent.learner_subject_id == subject_id)
            .order_by(KnowledgeEvidenceEvent.created_at)
        ).all()
        if not events:
            return {}
        unit_ids = {event.knowledge_unit_id for event in events}
        units = {
            unit.id: unit
            for unit in self.db.scalars(
                select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids))
            ).all()
        }
        grouped: dict[str, list[KnowledgeEvidenceEvent]] = defaultdict(list)
        for event in events:
            unit = units.get(event.knowledge_unit_id)
            grouped[unit.code if unit else event.knowledge_unit_id].append(event)
        result = {}
        for code, items in grouped.items():
            total = sum(item.evidence_weight for item in items)
            mastery = sum(item.observation * item.evidence_weight for item in items) / max(total, 0.01)
            last_unit = units.get(items[-1].knowledge_unit_id)
            misconceptions: dict[str, dict[str, Any]] = {}
            for event in items:
                for error in event.detected_misconceptions or []:
                    item_code = misconception_code(error)
                    item = misconceptions.setdefault(
                        item_code,
                        {"code": item_code, "text": error, "status": "active", "occurrences": 0},
                    )
                    item["status"] = "active"
                    item["occurrences"] += 1
                for resolved_code in event.resolved_misconceptions or []:
                    if resolved_code in misconceptions:
                        misconceptions[resolved_code]["status"] = "resolved"
            result[code] = {
                "knowledge_unit_id": items[-1].knowledge_unit_id,
                "code": code,
                "name": last_unit.name if last_unit else code,
                "mastery": round(clamp(mastery), 6),
                "confidence": round(1.0 - math.exp(-total / 1.5), 6),
                "evidence_count": len(items),
                "total_evidence_weight": round(total, 6),
                "misconceptions": list(misconceptions.values()),
                "last_tested_at": items[-1].created_at.isoformat(),
            }
        return result

    @staticmethod
    def _update_misconceptions(
        existing: list[dict[str, Any]], errors: list[str], observation: float, evidence_count: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        by_code = {item.get("code"): dict(item) for item in existing if item.get("code")}
        for error in errors:
            code = misconception_code(error)
            item = by_code.setdefault(code, {"code": code, "text": error, "status": "suspected"})
            item["status"] = "active"
            item["occurrences"] = int(item.get("occurrences", 0)) + 1
        resolved = []
        if not errors and observation >= 0.80 and evidence_count >= 2:
            for item in by_code.values():
                if item.get("status") == "active":
                    item["status"] = "resolved"
                    resolved.append(str(item["code"]))
        return list(by_code.values()), resolved

    @staticmethod
    def _apply_observation(
        state: KnowledgeState, event: KnowledgeEvidenceEvent, misconceptions: list[dict[str, Any]]
    ) -> None:
        prior_weight = float(state.total_evidence_weight or 0.0)
        total_weight = prior_weight + event.evidence_weight
        mastery = (
            float(state.mastery or 0.0) * prior_weight + event.observation * event.evidence_weight
        ) / max(total_weight, 0.01)
        evidence_count = int(state.evidence_count or 0) + 1
        if evidence_count < 2:
            mastery = min(mastery, 0.85)
        state.mastery = clamp(mastery)
        state.confidence = clamp(1.0 - math.exp(-total_weight / 1.5))
        state.evidence_count = evidence_count
        state.correct_evidence_count = int(state.correct_evidence_count or 0) + int(
            event.observation >= 0.70
        )
        state.total_evidence_weight = total_weight
        state.misconceptions = misconceptions
        state.last_tested_at = event.created_at
        state.updated_at = utcnow()

    def _update_compatibility_snapshot(
        self, session: ExamSession, units: dict[str, dict[str, Any]]
    ) -> None:
        snapshot = dict(session.mastery_state or {})
        knowledge = {}
        for state in self.db.scalars(
            select(KnowledgeState).where(KnowledgeState.session_id == session.id)
        ).all():
            unit = units.get(state.knowledge_unit_id, {})
            knowledge[unit.get("code", state.knowledge_unit_id)] = {
                **self.serialize_state(state),
                "name": unit.get("name", state.knowledge_unit_id),
                "importance": unit.get("importance", 0.7),
            }
        snapshot["_knowledge"] = knowledge
        session.mastery_state = snapshot

    @staticmethod
    def serialize_unit(unit: KnowledgeUnit) -> dict[str, Any]:
        return {
            "id": unit.id,
            "code": unit.code,
            "name": unit.name,
            "description": unit.description,
            "importance": unit.importance,
            "default_difficulty": unit.default_difficulty,
            "prerequisite_codes": unit.prerequisite_codes or [],
            "misconception_catalog": unit.misconception_catalog or [],
            "source_evidence_asset_ids": unit.source_evidence_asset_ids or [],
        }

    @staticmethod
    def serialize_state(state: KnowledgeState) -> dict[str, Any]:
        return {
            "id": state.id,
            "knowledge_unit_id": state.knowledge_unit_id,
            "mastery": round(float(state.mastery), 6),
            "confidence": round(float(state.confidence), 6),
            "evidence_count": state.evidence_count,
            "correct_evidence_count": state.correct_evidence_count,
            "total_evidence_weight": round(float(state.total_evidence_weight), 6),
            "misconceptions": state.misconceptions or [],
            "last_tested_at": state.last_tested_at.isoformat() if state.last_tested_at else None,
            "updated_at": state.updated_at.isoformat(),
        }
