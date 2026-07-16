from __future__ import annotations

from collections import defaultdict


class ReportGenerator:
    name = "report_generator"

    def generate(self, *, blueprint: dict, turns: list[dict], mastery_state: dict) -> dict:
        evaluations = [t for t in turns if t.get("role") == "user" and t.get("evaluation")]
        scores = [float(t["evaluation"].get("score", 0)) for t in evaluations]
        average = round(sum(scores) / len(scores), 2) if scores else 0.0
        by_type: dict[str, list[float]] = defaultdict(list)
        weaknesses: list[str] = []
        strengths: list[str] = []
        evidence: list[dict] = []
        question_map = {q.get("id"): q for q in blueprint.get("questions") or []}
        for turn in evaluations:
            evaluation = turn["evaluation"]
            by_type[evaluation.get("question_type", "general")].append(
                float(evaluation.get("score", 0))
            )
            weaknesses.extend(evaluation.get("missing_points", []))
            weaknesses.extend(evaluation.get("errors", []))
            if float(evaluation.get("score", 0)) >= 3.8:
                strengths.append(evaluation.get("supporting_quote", "")[:120])
            question = question_map.get(turn.get("question_id"), {})
            evidence.append(
                {
                    "question_id": turn.get("question_id"),
                    "score": evaluation.get("score"),
                    "quote": evaluation.get("supporting_quote"),
                    "missing_points": evaluation.get("missing_points", []),
                    "source_page": question.get("source_page"),
                    "source_excerpt": question.get("source_excerpt"),
                    "evidence_asset_ids": question.get("evidence_asset_ids", []),
                    "page_preview_url": question.get("page_preview_url"),
                }
            )
        dimension_summary = {
            key: round(sum(values) / len(values), 2) for key, values in by_type.items()
        }
        risk_level = "high" if average < 2.5 else ("medium" if average < 3.7 else "low")
        return {
            "title": blueprint.get("title", "AI 答辩报告"),
            "overall_score": average,
            "max_score": 5,
            "risk_level": risk_level,
            "questions_answered": len(evaluations),
            "dimension_summary": dimension_summary,
            "strengths": [x for x in strengths[:5] if x],
            "priority_weaknesses": list(dict.fromkeys(x for x in weaknesses if x))[:8],
            "evidence": evidence,
            "mastery_state": mastery_state,
            "recommended_actions": [
                "针对优先薄弱点重新组织一段不超过两分钟的回答。",
                "为每个主要结论补充一个直接证据、一个边界条件和一个反例。",
                "复测时优先使用反事实、泛化与局限类问题，而不是重复定义题。",
            ],
            "disclaimer": "本报告用于训练和辅助判断，不应作为正式学位、招聘或人事决定的唯一依据。",
        }
