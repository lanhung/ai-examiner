from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ExpertRating, GoldenDataset

DIMENSIONS = ("relevance", "difficulty", "groundedness", "answer_quality")


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_var * right_var)
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def agreement_summary(db: Session, dataset: GoldenDataset) -> dict:
    ratings = db.scalars(
        select(ExpertRating).where(ExpertRating.golden_dataset_id == dataset.id)
    ).all()
    by_case: dict[str, list[ExpertRating]] = defaultdict(list)
    for rating in ratings:
        by_case[rating.case_id].append(rating)

    case_lookup = {case.get("id"): case for case in dataset.data.get("cases") or []}
    case_summaries = []
    ai_values: list[float] = []
    human_values: list[float] = []

    for case_id, case_ratings in sorted(by_case.items()):
        dimension_means = {
            dimension: round(
                mean(float(rating.ratings.get(dimension, 0)) for rating in case_ratings), 3
            )
            for dimension in DIMENSIONS
        }
        human_overall = mean(dimension_means.values())
        case = case_lookup.get(case_id, {})
        quality = case.get("quality_scores") or {}
        ai_dimensions = [
            float(quality[key])
            for key in ("relevance", "groundedness", "clarity", "answerability")
            if isinstance(quality.get(key), (int, float))
        ]
        ai_overall = mean(ai_dimensions) if ai_dimensions else None
        if ai_overall is not None:
            ai_values.append(ai_overall)
            human_values.append(human_overall)
        case_summaries.append(
            {
                "case_id": case_id,
                "rater_count": len(case_ratings),
                "human_dimension_means": dimension_means,
                "human_overall": round(human_overall, 3),
                "ai_overall": round(ai_overall, 3) if ai_overall is not None else None,
                "absolute_gap": (
                    round(abs(ai_overall - human_overall), 3)
                    if ai_overall is not None
                    else None
                ),
            }
        )

    gaps = [item["absolute_gap"] for item in case_summaries if item["absolute_gap"] is not None]
    return {
        "dataset_id": dataset.id,
        "rating_count": len(ratings),
        "rated_case_count": len(by_case),
        "case_count": len(case_lookup),
        "coverage": round(len(by_case) / max(1, len(case_lookup)), 3),
        "ai_human_pearson": _pearson(ai_values, human_values),
        "mean_absolute_gap": round(mean(gaps), 3) if gaps else None,
        "cases": case_summaries,
        "note": (
            "This endpoint supports optional expert calibration; the Golden Dataset itself is generated "
            "by the multi-model panel."
        ),
    }
