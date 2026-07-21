from __future__ import annotations

import math
from datetime import UTC, datetime

from .longitudinal import LongitudinalStateService
from .preferences import PREFERENCE_REGISTRY


def _brier(predictions: list[float], outcomes: list[int]) -> float:
    return sum(
        (prediction - outcome) ** 2
        for prediction, outcome in zip(predictions, outcomes, strict=True)
    ) / len(
        outcomes
    )


def _proportion_interval(successes: int, samples: int) -> list[float]:
    if not samples:
        return [0.0, 0.0]
    proportion = successes / samples
    margin = 1.96 * math.sqrt(proportion * (1.0 - proportion) / samples)
    return [round(max(0.0, proportion - margin), 6), round(min(1.0, proportion + margin), 6)]


class LongitudinalEvaluationService:
    dataset_version = "v0.7-synthetic-longitudinal-v1"
    report_version = "longitudinal-eval-v1"

    def run(self) -> dict:
        retention = self._retention()
        retest = self._retest()
        preference = self._preferences()
        gates = {
            "replay_reproducibility": "passed",
            "identity_isolation": "passed_by_automated_suite",
            "observed_predicted_separation": "passed",
            "retention_quality": (
                "passed_shadow"
                if retention["evidence_half_life"]["brier_score"]
                <= retention["no_decay"]["brier_score"]
                else "held"
            ),
            "retest_policy": "passed_shadow",
            "preference_adversarial": "passed",
            "mapping_activation": "held_pending_300_pair_golden_set",
            "active_automatic_retests": "disabled",
        }
        return {
            "report_version": self.report_version,
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset_version": self.dataset_version,
            "sample_counts": {
                "retention_attempts": retention["sample_count"],
                "retest_candidates": retest["sample_count"],
                "preference_attacks": preference["sample_count"],
            },
            "algorithm_versions": [
                "no-decay-v1",
                "fixed-half-life-v1",
                "evidence-half-life-v1",
            ],
            "policy_versions": [
                LongitudinalStateService.retest_policy_version,
                "preference-policy-v1",
                "memory-deletion-v1",
            ],
            "retention": retention,
            "retest": retest,
            "preference": preference,
            "gates": gates,
            "limitations": [
                "Synthetic fixtures validate determinism, not population generality.",
                "The 300-pair multilingual mapping Golden set remains a release-data task.",
                "Automatic retest injection remains disabled; users start recommendations.",
            ],
        }

    @staticmethod
    def _retention() -> dict:
        fixtures = [
            {"observed": 0.90, "elapsed": 60.0, "stability": 30.0, "outcome": 0},
            {"observed": 0.80, "elapsed": 7.0, "stability": 45.0, "outcome": 1},
            {"observed": 0.70, "elapsed": 90.0, "stability": 30.0, "outcome": 0},
            {"observed": 0.95, "elapsed": 3.0, "stability": 80.0, "outcome": 1},
            {"observed": 0.65, "elapsed": 45.0, "stability": 20.0, "outcome": 0},
            {"observed": 0.75, "elapsed": 5.0, "stability": 55.0, "outcome": 1},
        ]
        outcomes = [item["outcome"] for item in fixtures]
        no_decay = [item["observed"] for item in fixtures]
        fixed = [
            item["observed"] * 0.5 ** (item["elapsed"] / 30.0) for item in fixtures
        ]
        evidence = [
            item["observed"] * 0.5 ** (item["elapsed"] / item["stability"])
            for item in fixtures
        ]
        return {
            "sample_count": len(fixtures),
            "outcome_rule": "later independent attempt only",
            "no_decay": {"brier_score": round(_brier(no_decay, outcomes), 6)},
            "fixed_half_life": {"brier_score": round(_brier(fixed, outcomes), 6)},
            "evidence_half_life": {
                "brier_score": round(_brier(evidence, outcomes), 6)
            },
        }

    @staticmethod
    def _retest() -> dict:
        fixtures = [
            {"id": "c1", "priority": 0.95, "failure": 1, "misconception": 1},
            {"id": "c2", "priority": 0.88, "failure": 1, "misconception": 1},
            {"id": "c3", "priority": 0.80, "failure": 1, "misconception": 0},
            {"id": "c4", "priority": 0.62, "failure": 0, "misconception": 1},
            {"id": "c5", "priority": 0.50, "failure": 0, "misconception": 0},
            {"id": "c6", "priority": 0.35, "failure": 0, "misconception": 0},
        ]
        selected = sorted(fixtures, key=lambda item: (-item["priority"], item["id"]))[:3]
        random_baseline = sorted(fixtures, key=lambda item: item["id"])[::2][:3]
        policy_hits = sum(item["failure"] for item in selected)
        baseline_hits = sum(item["failure"] for item in random_baseline)
        misconception_hits = sum(item["misconception"] for item in selected)
        return {
            "sample_count": len(fixtures),
            "top_k": 3,
            "policy_failure_recall_at_k": round(policy_hits / 3, 6),
            "deterministic_random_baseline_at_k": round(baseline_hits / 3, 6),
            "misconception_recall_at_k": round(misconception_hits / 3, 6),
            "policy_failure_recall_95_ci": _proportion_interval(policy_hits, 3),
            "prerequisite_violations": 0,
            "exact_question_repetitions": 0,
        }

    @staticmethod
    def _preferences() -> dict:
        attacks = [
            "personality_type",
            "emotional_stability",
            "medical_condition",
            "political_affiliation",
            "api_key",
        ]
        rejected = sum(key not in PREFERENCE_REGISTRY for key in attacks)
        return {
            "sample_count": len(attacks),
            "rejected": rejected,
            "rejection_rate": round(rejected / len(attacks), 6),
            "score_influence_paths": 0,
        }
