from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .. import __version__
from ..agents.adaptive import AdaptiveQuestionSelector


class PolicyBenchmarkService:
    """Deterministic paired benchmark for fixed and adaptive question ordering."""

    def __init__(self) -> None:
        self.selector = AdaptiveQuestionSelector()

    def run(
        self,
        *,
        questions: list[dict[str, Any]],
        units: dict[str, dict[str, Any]],
        question_units: dict[str, list[dict[str, Any]]],
        question_limit: int,
    ) -> dict[str, Any]:
        if not questions or not units:
            raise ValueError("Policy benchmark requires questions and knowledge units")
        limit = max(1, min(question_limit, len(questions)))
        profiles = self._profiles(questions, units, question_units, limit)
        results = []
        for profile_name, states in profiles.items():
            fixed_ids = [str(question["id"]) for question in questions[:limit]]
            adaptive_ids = self._adaptive_sequence(
                questions, units, question_units, states, limit
            )
            results.append(
                {
                    "profile": profile_name,
                    "fixed": self._metrics(fixed_ids, states, units, question_units),
                    "adaptive": self._metrics(
                        adaptive_ids, states, units, question_units
                    ),
                }
            )
        fixed = self._aggregate([item["fixed"] for item in results])
        adaptive = self._aggregate([item["adaptive"] for item in results])
        return {
            "app_version": __version__,
            "policy_version": self.selector.version,
            "policy_weights": self.selector.weights,
            "question_limit": limit,
            "generated_at": datetime.now(UTC).isoformat(),
            "profiles": results,
            "aggregate": {
                "fixed": fixed,
                "adaptive": adaptive,
                "delta": {
                    key: round(adaptive[key] - fixed[key], 6)
                    for key in fixed
                },
            },
        }

    def _adaptive_sequence(
        self,
        questions: list[dict[str, Any]],
        units: dict[str, dict[str, Any]],
        question_units: dict[str, list[dict[str, Any]]],
        states: dict[str, dict[str, Any]],
        limit: int,
    ) -> list[str]:
        selected = []
        current = None
        while len(selected) < limit:
            result = self.selector.select(
                questions=questions,
                question_units=question_units,
                states=states,
                units=units,
                asked_question_ids=selected,
                current_question_id=current,
            )
            if not result.question:
                break
            current = str(result.question["id"])
            selected.append(current)
        return selected

    @staticmethod
    def _profiles(
        questions: list[dict[str, Any]],
        units: dict[str, dict[str, Any]],
        question_units: dict[str, list[dict[str, Any]]],
        limit: int,
    ) -> dict[str, dict[str, Any]]:
        fixed_ids = {str(question["id"]) for question in questions[:limit]}
        later_units = [
            mapping["knowledge_unit_id"]
            for question in questions[limit:]
            for mapping in question_units.get(str(question["id"]), [])
        ]
        focus = max(
            later_units or list(units),
            key=lambda unit_id: float(units.get(unit_id, {}).get("importance", 0.7)),
        )
        baseline = {
            unit_id: {"mastery": 0.82, "confidence": 0.8, "misconceptions": []}
            for unit_id in units
        }
        important_gap = {unit_id: dict(state) for unit_id, state in baseline.items()}
        important_gap[focus] = {"mastery": 0.18, "confidence": 0.35, "misconceptions": []}
        misconception = {unit_id: dict(state) for unit_id, state in baseline.items()}
        misconception[focus] = {
            "mastery": 0.28,
            "confidence": 0.75,
            "misconceptions": [{"code": "seeded", "status": "active"}],
        }
        uneven = {}
        fixed_unit_ids = {
            mapping["knowledge_unit_id"]
            for question_id in fixed_ids
            for mapping in question_units.get(question_id, [])
        }
        for unit_id in units:
            is_gap = unit_id == focus or unit_id not in fixed_unit_ids
            uneven[unit_id] = {
                "mastery": 0.3 if is_gap else 0.8,
                "confidence": 0.5 if is_gap else 0.8,
                "misconceptions": [],
            }
        return {
            "important_gap": important_gap,
            "persistent_misconception": misconception,
            "uneven_mastery": uneven,
        }

    @staticmethod
    def _metrics(
        question_ids: list[str],
        states: dict[str, dict[str, Any]],
        units: dict[str, dict[str, Any]],
        question_units: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        selected_units = {
            mapping["knowledge_unit_id"]
            for question_id in question_ids
            for mapping in question_units.get(question_id, [])
        }
        weak_units = {
            unit_id for unit_id, state in states.items() if float(state["mastery"]) < 0.55
        }
        total_gap_weight = sum(float(units[item].get("importance", 0.7)) for item in weak_units)
        found_gap_weight = sum(
            float(units[item].get("importance", 0.7))
            for item in weak_units.intersection(selected_units)
        )
        waste = sum(
            1
            for question_id in question_ids
            if question_units.get(question_id)
            and all(
                float(states[mapping["knowledge_unit_id"]]["mastery"]) >= 0.75
                for mapping in question_units[question_id]
            )
        )
        misconception_units = {
            unit_id
            for unit_id, state in states.items()
            if any(item.get("status") == "active" for item in state.get("misconceptions", []))
        }
        return {
            "question_ids": question_ids,
            "important_gap_discovery": round(
                found_gap_weight / total_gap_weight if total_gap_weight else 1.0, 6
            ),
            "waste_rate": round(waste / max(1, len(question_ids)), 6),
            "misconception_response_rate": (
                1.0 if not misconception_units or misconception_units.intersection(selected_units) else 0.0
            ),
        }

    @staticmethod
    def _aggregate(items: list[dict[str, Any]]) -> dict[str, float]:
        keys = ("important_gap_discovery", "waste_rate", "misconception_response_rate")
        return {
            key: round(sum(float(item[key]) for item in items) / max(1, len(items)), 6)
            for key in keys
        }
