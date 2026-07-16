from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class SelectionResult:
    question: dict[str, Any] | None
    target_difficulty: int
    reason_codes: list[str]
    candidate_scores: list[dict[str, Any]]


class DifficultyController:
    name = "difficulty_controller"
    version = "difficulty-v1"

    def target(self, states: list[dict[str, Any]]) -> int:
        if not states:
            return 2
        total_weight = sum(max(0.1, float(state.get("importance", 0.7))) for state in states)
        mastery = sum(
            float(state.get("mastery", 0.0)) * max(0.1, float(state.get("importance", 0.7)))
            for state in states
        ) / total_weight
        has_active_misconception = any(
            item.get("status") == "active"
            for state in states
            for item in state.get("misconceptions", [])
        )
        if mastery < 0.30:
            level = 2
        elif mastery < 0.55:
            level = 3
        elif mastery < 0.75:
            level = 4
        else:
            level = 5
        if has_active_misconception:
            level = max(2, level - 1)
        return level


class AdaptiveQuestionSelector:
    name = "adaptive_question_selector"
    version = "adaptive-v1"
    weights = {
        "knowledge_gap": 0.30,
        "uncertainty": 0.20,
        "importance": 0.20,
        "misconception_priority": 0.15,
        "difficulty_fit": 0.10,
        "novelty": 0.05,
    }

    def __init__(self) -> None:
        self.difficulty = DifficultyController()

    def select(
        self,
        *,
        questions: list[dict[str, Any]],
        question_units: dict[str, list[dict[str, Any]]],
        states: dict[str, dict[str, Any]],
        units: dict[str, dict[str, Any]],
        asked_question_ids: list[str],
        current_question_id: str | None = None,
        prior_question_ids: list[str] | None = None,
    ) -> SelectionResult:
        enriched_states = []
        for unit_id, state in states.items():
            enriched_states.append({**state, "importance": units.get(unit_id, {}).get("importance", 0.7)})
        target = self.difficulty.target(enriched_states)
        asked = set(asked_question_ids)
        prior = set(prior_question_ids or [])
        current_units = {
            item["knowledge_unit_id"] for item in question_units.get(current_question_id or "", [])
        }
        code_to_id = {unit.get("code"): unit_id for unit_id, unit in units.items()}
        candidates: list[dict[str, Any]] = []

        for question in questions:
            question_id = str(question.get("id", ""))
            if not question_id or question_id in asked:
                continue
            mappings = question_units.get(question_id, [])
            linked_ids = [item["knowledge_unit_id"] for item in mappings]
            linked_units = [units[unit_id] for unit_id in linked_ids if unit_id in units]
            if not linked_units:
                continue

            prerequisites = {
                code
                for unit in linked_units
                for code in unit.get("prerequisite_codes", [])
                if code
            }
            unmet = [
                code
                for code in prerequisites
                if states.get(code_to_id.get(code, ""), {}).get("mastery", 0.0) < 0.35
            ]
            if unmet:
                continue

            # Untested knowledge is uncertain, not proof of zero mastery. A conservative
            # prior keeps broad coverage useful without outranking an observed misconception.
            mapped_states = [
                states.get(
                    unit_id,
                    {"mastery": 0.35, "confidence": 0.15, "misconceptions": []},
                )
                for unit_id in linked_ids
            ]
            mastery = sum(float(state.get("mastery", 0.0)) for state in mapped_states) / max(
                1, len(mapped_states)
            )
            confidence = sum(float(state.get("confidence", 0.0)) for state in mapped_states) / max(
                1, len(mapped_states)
            )
            importance = sum(float(unit.get("importance", 0.7)) for unit in linked_units) / len(
                linked_units
            )
            active_misconception = any(
                item.get("status") == "active"
                for state in mapped_states
                for item in state.get("misconceptions", [])
            )
            difficulty = max(1, min(5, int(question.get("difficulty", 3))))
            if question_id in prior:
                novelty = 0.1
            elif current_units.intersection(linked_ids):
                novelty = 0.4
            else:
                novelty = 1.0
            components = {
                "knowledge_gap": clamp(1.0 - mastery),
                "uncertainty": clamp(1.0 - confidence),
                "importance": clamp(importance),
                "misconception_priority": 1.0 if active_misconception else 0.0,
                "difficulty_fit": clamp(1.0 - abs(difficulty - target) / 4.0),
                "novelty": novelty,
            }
            total = sum(self.weights[key] * value for key, value in components.items())
            candidates.append(
                {
                    "question_id": question_id,
                    "difficulty": difficulty,
                    "total": round(total, 6),
                    **{key: round(value, 6) for key, value in components.items()},
                }
            )

        candidates.sort(key=lambda item: (-item["total"], item["question_id"]))
        if not candidates:
            return SelectionResult(None, target, ["no_eligible_question"], [])
        selected = candidates[0]
        question = next(q for q in questions if str(q.get("id")) == selected["question_id"])
        reasons = [
            key
            for key in ("misconception_priority", "knowledge_gap", "importance", "uncertainty")
            if selected.get(key, 0.0) >= 0.7
        ] or ["best_available_candidate"]
        return SelectionResult(question, target, reasons, candidates)
