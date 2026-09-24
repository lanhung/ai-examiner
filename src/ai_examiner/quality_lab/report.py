from __future__ import annotations

from typing import Any


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _usd(value: float | None) -> str:
    return "–" if value is None else f"${value:.5f}"


def render_markdown(summary: dict[str, Any], *, heuristic_judge: bool) -> str:
    lines = ["# AI Examiner quality lab report", ""]
    totals = summary["totals"]
    lines += [
        f"- Blueprints: {totals['blueprints']}; sessions: {totals['sessions']}; "
        f"answers: {totals['answers']}",
        f"- System model cost: {_usd(totals['model_cost_usd'])}; judge cost: "
        f"{_usd(totals['judge_cost_usd'])}",
        f"- Quality index weights: {summary['weights']}",
    ]
    if heuristic_judge:
        lines += [
            "",
            "> **Heuristic judge.** This run used the offline heuristic judge and/or mock "
            "models. The numbers prove the pipeline works; they do not rank real models.",
        ]
    recommendation = summary["recommendation"]
    lines += [
        "",
        "## Recommendation",
        "",
        f"- Highest quality: `{recommendation.get('best_quality')}`",
        f"- Recommended (cheapest within {recommendation.get('tolerance')} of best): "
        f"`{recommendation.get('recommended')}`",
        f"- Quality given up: {_fmt(recommendation.get('quality_given_up'))}; "
        f"cost saving: {_fmt(recommendation.get('cost_saving_ratio'))}",
        f"- Eligibility: {recommendation.get('eligibility') or recommendation.get('reason')}",
        "",
        "Pareto frontier among eligible combinations (no other is both cheaper and better):",
        "",
    ]
    lines += [f"- `{combo}`" for combo in summary["pareto_frontier"]] or ["- none"]
    lines += [
        "",
        "## Combinations",
        "",
        "| Combination (planner × analyzer) | Quality | Questions | Grading | Follow-ups | Reliability | "
        "Spearman | False pass | Strong fail | Injection | Judge MAE | $/learner session | "
        "p95 ms/answer |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in summary["combinations"]:
        metrics = row["metrics"]
        grading = metrics["grading"]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row['combo']}`",
                    _fmt(metrics["quality_index"]),
                    _fmt(metrics["questions"]["score"]),
                    _fmt(grading["score"]),
                    _fmt(metrics["followups"]["score"]),
                    _fmt(metrics["reliability"]),
                    _fmt(grading["spearman_tier_vs_score"]),
                    _fmt(grading["false_pass_rate"]),
                    _fmt(grading["strong_fail_rate"]),
                    _fmt(grading["injection_success_rate"]),
                    _fmt(grading["judge_mae"]),
                    _usd(metrics["cost"]["usd_per_learner_session"]),
                    _fmt(metrics["latency_ms_per_answer"]["p95"]),
                ]
            )
            + " |"
        )
    lines += ["", "### Mean first-answer score by simulated learner", ""]
    personas = sorted(
        {
            persona
            for row in summary["combinations"]
            for persona in row["metrics"]["grading"]["mean_score_by_persona"]
        }
    )
    lines += [
        "| Combination | " + " | ".join(personas) + " |",
        "|---|" + "---|" * len(personas),
    ]
    for row in summary["combinations"]:
        scores = row["metrics"]["grading"]["mean_score_by_persona"]
        lines.append(
            f"| `{row['combo']}` | "
            + " | ".join(_fmt(scores.get(persona)) for persona in personas)
            + " |"
        )
    lines += [
        "",
        "## By domain (all combinations pooled)",
        "",
        "| Domain | Questions rated | Question quality | Leak rate | Factual errors | "
        "Grading | Spearman | False pass |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in summary["by_domain"]:
        questions, grading = row["questions"], row["grading"]
        lines.append(
            f"| {row['domain']} | {questions['n']} | {_fmt(questions['score'])} | "
            f"{_fmt(questions.get('leak_rate'))} | {_fmt(questions.get('factual_error_rate'))} | "
            f"{_fmt(grading['score'])} | {_fmt(grading['spearman_tier_vs_score'])} | "
            f"{_fmt(grading['false_pass_rate'])} |"
        )
    errors = [
        (row["combo"], error)
        for row in summary["combinations"]
        for error in row["metrics"]["errors"]
    ]
    if errors:
        lines += ["", "## Errors (first per combination)", ""]
        lines += [f"- `{combo}`: {error}" for combo, error in errors[:30]]
    unpriced = sorted(
        {
            model
            for row in summary["combinations"]
            for model in row["metrics"]["cost"]["unpriced_models"]
        }
    )
    if unpriced:
        lines += [
            "",
            f"**Unpriced models** (cost counted as $0; pass `--price`): {', '.join(unpriced)}",
        ]
    return "\n".join(lines) + "\n"
