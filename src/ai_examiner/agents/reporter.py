from __future__ import annotations

from collections import defaultdict
from typing import Any


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


class ReportGenerator:
    name = "report_generator"

    @staticmethod
    def _trajectory(question_id: str, turns: list[dict[str, Any]]) -> dict[str, Any]:
        independent = next(
            (
                turn
                for turn in turns
                if (turn.get("analysis") or {}).get("question_context", "main") == "main"
            ),
            turns[0],
        )
        final = turns[-1]
        independent_score = float(independent["evaluation"].get("score", 0.0))
        final_score = float(final["evaluation"].get("score", 0.0))
        followups = [
            turn
            for turn in turns
            if (turn.get("analysis") or {}).get("question_context") == "followup"
        ]
        remaining_gaps = list(
            dict.fromkeys(
                [
                    *list(final["evaluation"].get("missing_points") or []),
                    *list(final["evaluation"].get("errors") or []),
                ]
            )
        )
        return {
            "question_id": question_id,
            "independent_turn_id": independent.get("id"),
            "final_turn_id": final.get("id"),
            "independent_score": round(independent_score, 2),
            "final_assisted_score": round(final_score, 2),
            "followup_count": len(followups),
            "assistance_level": "followup" if followups else "direct",
            "learning_gain": round(final_score - independent_score, 2),
            "remaining_gaps": remaining_gaps,
            "final_confidence": float(final["evaluation"].get("confidence", 0.5)),
            "final_quote": str(final["evaluation"].get("supporting_quote") or "")[:260],
        }

    def generate(
        self,
        *,
        blueprint: dict,
        turns: list[dict],
        mastery_state: dict,
        knowledge_states: list[dict] | None = None,
        mode: str = "defense",
    ) -> dict:
        evaluations = [
            turn for turn in turns if turn.get("role") == "user" and turn.get("evaluation")
        ]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        question_order: list[str] = []
        for turn in evaluations:
            question_id = str(turn.get("question_id") or "unknown")
            if question_id not in grouped:
                question_order.append(question_id)
            grouped[question_id].append(turn)
        trajectories = [
            self._trajectory(question_id, grouped[question_id])
            for question_id in question_order
        ]

        independent_scores = [float(item["independent_score"]) for item in trajectories]
        assisted_scores = [float(item["final_assisted_score"]) for item in trajectories]
        if mode == "teaching":
            aggregate_scores = [
                0.7 * independent + 0.3 * assisted
                for independent, assisted in zip(independent_scores, assisted_scores, strict=True)
            ]
            score_policy = "teaching-70-independent-30-assisted-v1"
        else:
            aggregate_scores = independent_scores
            score_policy = "independent-main-answer-v1"
        overall = _average(aggregate_scores)

        by_type: dict[str, list[float]] = defaultdict(list)
        strengths: list[str] = []
        evidence: list[dict[str, Any]] = []
        weakness_evidence: list[dict[str, Any]] = []
        question_map = {str(question.get("id")): question for question in blueprint.get("questions") or []}

        for trajectory in trajectories:
            question_id = str(trajectory["question_id"])
            question = question_map.get(question_id, {})
            independent = grouped[question_id][0]
            for turn in grouped[question_id]:
                if (turn.get("analysis") or {}).get("question_context", "main") == "main":
                    independent = turn
                    break
            by_type[independent["evaluation"].get("question_type", "general")].append(
                float(independent["evaluation"].get("score", 0.0))
            )
            final_turn = grouped[question_id][-1]
            if float(trajectory["final_assisted_score"]) >= 3.8:
                quote = str(final_turn["evaluation"].get("supporting_quote") or "")[:120]
                if quote:
                    strengths.append(quote)
            final_gaps = trajectory["remaining_gaps"]
            for gap in final_gaps:
                weakness_evidence.append(
                    {
                        "question_id": question_id,
                        "statement": gap,
                        "turn_id": final_turn.get("id"),
                        "answer_quote": trajectory["final_quote"],
                        "source_excerpt": question.get("source_excerpt"),
                        "confidence": trajectory["final_confidence"],
                    }
                )

        for turn in evaluations:
            evaluation = turn["evaluation"]
            question = question_map.get(str(turn.get("question_id")), {})
            evidence.append(
                {
                    "turn_id": turn.get("id"),
                    "question_id": turn.get("question_id"),
                    "question_context": (turn.get("analysis") or {}).get(
                        "question_context", "main"
                    ),
                    "score": evaluation.get("score"),
                    "quote": evaluation.get("supporting_quote"),
                    "missing_points": evaluation.get("missing_points", []),
                    "point_assessments": evaluation.get("point_assessments", []),
                    "source_page": question.get("source_page"),
                    "source_excerpt": question.get("source_excerpt"),
                    "evidence_asset_ids": question.get("evidence_asset_ids", []),
                    "page_preview_url": question.get("page_preview_url"),
                }
            )

        dimension_summary = {
            key: _average(values) for key, values in by_type.items()
        }
        risk_level = "high" if overall < 2.5 else ("medium" if overall < 3.7 else "low")
        knowledge_map = []
        weakness_map = []
        for item in knowledge_states or []:
            unit = item.get("unit", {})
            mastery = float(item.get("mastery", 0.0))
            confidence = float(item.get("confidence", 0.0))
            active_misconceptions = [
                misconception
                for misconception in item.get("misconceptions", [])
                if misconception.get("status") == "active"
            ]
            knowledge_item = {
                "knowledge_unit_id": item.get("knowledge_unit_id"),
                "code": unit.get("code", item.get("knowledge_unit_id")),
                "name": unit.get("name", item.get("knowledge_unit_id")),
                "importance": unit.get("importance", 0.7),
                "mastery": round(mastery, 3),
                "confidence": round(confidence, 3),
                "evidence_count": item.get("evidence_count", 0),
                "status": "mastered"
                if mastery >= 0.75 and confidence >= 0.6
                else ("developing" if mastery >= 0.45 else "gap"),
                "misconceptions": active_misconceptions,
                "evidence": item.get("evidence", []),
            }
            knowledge_map.append(knowledge_item)
            if mastery < 0.60 or active_misconceptions:
                weakness_map.append(knowledge_item)
        knowledge_map.sort(key=lambda item: (-float(item["importance"]), item["name"]))
        weakness_map.sort(
            key=lambda item: (
                float(item["mastery"]),
                -float(item["importance"]),
                item["name"],
            )
        )
        improvement_path = [
            f"优先复测 {item['name']}：当前掌握度 {item['mastery']:.0%}，"
            f"置信度 {item['confidence']:.0%}，建议使用高一级的应用或反例问题。"
            for item in weakness_map[:5]
        ]
        priority_weaknesses = list(
            dict.fromkeys(
                item["statement"]
                for item in weakness_evidence
                if item["statement"] and float(item["confidence"]) >= 0.5
            )
        )[:8]
        return {
            "report_version": "assessment-report-v2",
            "title": blueprint.get("title", "AI 答辩报告"),
            "mode": mode,
            "score_policy": score_policy,
            "overall_score": overall,
            "max_score": 5,
            "risk_level": risk_level,
            "questions_answered": len(trajectories),
            "evaluated_turns": len(evaluations),
            "assessment_summary": {
                "independent_average": _average(independent_scores),
                "assisted_average": _average(assisted_scores),
                "average_learning_gain": _average(
                    [float(item["learning_gain"]) for item in trajectories]
                ),
            },
            "question_trajectories": trajectories,
            "dimension_summary": dimension_summary,
            "strengths": list(dict.fromkeys(strengths))[:5],
            "priority_weaknesses": priority_weaknesses,
            "weakness_evidence": weakness_evidence,
            "evidence": evidence,
            "mastery_state": mastery_state,
            "knowledge_map": knowledge_map,
            "weakness_map": weakness_map,
            "improvement_path": improvement_path,
            "recommended_actions": [
                "针对优先薄弱点重新组织一段不超过两分钟的回答。",
                "为每个主要结论补充一个直接证据、一个边界条件和一个反例。",
                "复测时优先使用反事实、泛化与局限类问题，而不是重复定义题。",
            ],
            "disclaimer": (
                "本报告用于训练和辅助判断，不应作为正式学位、招聘或人事决定的唯一依据。"
            ),
        }
