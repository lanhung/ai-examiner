from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..services.template_assessment import (
    ASSISTED_BLEND,
    assessment_policy,
    disclaimer,
    localized_text,
    report_policy,
)


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _weighted_average(items: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in items)
    if total_weight <= 0:
        return 0.0
    return round(sum(value * weight for value, weight in items) / total_weight, 4)


class ReportGenerator:
    name = "report_generator"
    version = "assessment-report-v3"

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
        independent_score = float(
            independent["evaluation"].get(
                "computed_score", independent["evaluation"].get("score", 0.0)
            )
        )
        final_score = float(
            final["evaluation"].get(
                "computed_score", final["evaluation"].get("score", 0.0)
            )
        )
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

    @staticmethod
    def _attempt_score(
        trajectory: dict[str, Any],
        assisted_performance: str,
    ) -> float:
        independent = float(trajectory["independent_score"])
        assisted = float(trajectory["final_assisted_score"])
        if assisted_performance == "blend_with_independent":
            return round(
                ASSISTED_BLEND["independent"] * independent
                + ASSISTED_BLEND["assisted"] * assisted,
                4,
            )
        return independent

    @staticmethod
    def _dimension_map(evaluation: dict[str, Any]) -> dict[str, float]:
        assessments = evaluation.get("dimension_assessments") or []
        if assessments:
            return {
                str(item["id"]): float(item.get("score", 0.0))
                for item in assessments
            }
        return {
            str(key): float(value)
            for key, value in (evaluation.get("dimensions") or {}).items()
        }

    @classmethod
    def _selected_dimensions(
        cls,
        independent: dict[str, Any],
        final: dict[str, Any],
        assisted_performance: str,
    ) -> dict[str, float]:
        independent_map = cls._dimension_map(independent)
        if assisted_performance != "blend_with_independent":
            return independent_map
        final_map = cls._dimension_map(final)
        return {
            key: round(
                ASSISTED_BLEND["independent"] * value
                + ASSISTED_BLEND["assisted"] * final_map.get(key, value),
                4,
            )
            for key, value in independent_map.items()
        }

    @staticmethod
    def _knowledge_sections(
        knowledge_states: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        knowledge_map = []
        weakness_map = []
        for item in knowledge_states:
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
                "status": (
                    "mastered"
                    if mastery >= 0.75 and confidence >= 0.6
                    else ("developing" if mastery >= 0.45 else "gap")
                ),
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
            (
                f"优先复测 {item['name']}：当前掌握度 {item['mastery']:.0%}，"
                f"置信度 {item['confidence']:.0%}，建议使用高一级的应用或反例问题。"
            )
            for item in weakness_map[:5]
        ]
        return knowledge_map, weakness_map, improvement_path

    @staticmethod
    def _section_payloads(report: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": {
                "overall_score": report["overall_score"],
                "max_score": report["max_score"],
                "risk_level": report["risk_level"],
                "questions_answered": report["questions_answered"],
                "assessment_summary": report["assessment_summary"],
            },
            "objective_scores": report["objective_scores"],
            "dimension_scores": report["dimension_scores"],
            "evidence": report["evidence"],
            "strengths": report["strengths"],
            "weaknesses": {
                "priority": report["priority_weaknesses"],
                "evidence": report["weakness_evidence"],
            },
            "knowledge_map": report["knowledge_map"],
            "learning_gain": {
                "average": report["assessment_summary"]["average_learning_gain"],
                "trajectories": report["question_trajectories"],
            },
            "improvement_path": report["improvement_path"],
            "recommended_actions": report["recommended_actions"],
            "retest_plan": report.get("retest_plan", []),
        }

    def generate(
        self,
        *,
        blueprint: dict,
        turns: list[dict],
        mastery_state: dict,
        knowledge_states: list[dict] | None = None,
        mode: str = "defense",
        template_snapshot: dict[str, Any] | None = None,
        language: str = "zh-CN",
        template_fingerprint: str | None = None,
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
        question_map = {
            str(question.get("id")): question
            for question in blueprint.get("questions") or []
        }

        assessment_contract = assessment_policy(template_snapshot)
        report_contract = report_policy(template_snapshot)
        assisted_performance = str(
            assessment_contract.get("assisted_performance") or "report_separately"
        )
        if template_snapshot is None and mode == "teaching":
            assisted_performance = "blend_with_independent"
        selected_scores = [
            self._attempt_score(trajectory, assisted_performance)
            for trajectory in trajectories
        ]
        independent_scores = [
            float(item["independent_score"]) for item in trajectories
        ]
        assisted_scores = [
            float(item["final_assisted_score"]) for item in trajectories
        ]

        evidence: list[dict[str, Any]] = []
        weakness_evidence: list[dict[str, Any]] = []
        strengths: list[str] = []
        dimension_values: dict[str, list[float]] = defaultdict(list)
        dimension_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
        objective_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for trajectory, selected_score in zip(
            trajectories, selected_scores, strict=True
        ):
            question_id = str(trajectory["question_id"])
            question = question_map.get(question_id, {})
            turns_for_question = grouped[question_id]
            independent = next(
                (
                    item
                    for item in turns_for_question
                    if (item.get("analysis") or {}).get("question_context", "main")
                    == "main"
                ),
                turns_for_question[0],
            )
            final_turn = turns_for_question[-1]
            selected_dimensions = self._selected_dimensions(
                independent["evaluation"],
                final_turn["evaluation"],
                assisted_performance,
            )
            independent_dimension_details = {
                str(item["id"]): item
                for item in independent["evaluation"].get(
                    "dimension_assessments", []
                )
            }
            for dimension_id, value in selected_dimensions.items():
                dimension_values[dimension_id].append(value)
                detail = independent_dimension_details.get(dimension_id, {})
                dimension_evidence[dimension_id].append(
                    {
                        "question_id": question_id,
                        "turn_id": independent.get("id"),
                        "answer_quote": independent["evaluation"].get(
                            "supporting_quote"
                        ),
                        "score": value,
                        "rubric": detail.get("rubric"),
                        "evidence": detail.get("evidence", []),
                    }
                )
            objective_ids = list(
                question.get("objective_ids")
                or independent["evaluation"].get("objective_ids")
                or []
            )
            for objective_id in objective_ids:
                objective_evidence[str(objective_id)].append(
                    {
                        "question_id": question_id,
                        "turn_id": independent.get("id"),
                        "answer_quote": independent["evaluation"].get(
                            "supporting_quote"
                        ),
                        "score": selected_score,
                        "source_excerpt": question.get("source_excerpt"),
                        "dimension_assessments": independent["evaluation"].get(
                            "dimension_assessments", []
                        ),
                    }
                )
            if float(trajectory["final_assisted_score"]) >= 3.8:
                quote = str(
                    final_turn["evaluation"].get("supporting_quote") or ""
                )[:120]
                if quote:
                    strengths.append(quote)
            for gap in trajectory["remaining_gaps"]:
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
                    "dimension_assessments": evaluation.get(
                        "dimension_assessments", []
                    ),
                    "source_page": question.get("source_page"),
                    "source_excerpt": question.get("source_excerpt"),
                    "evidence_asset_ids": question.get("evidence_asset_ids", []),
                    "page_preview_url": question.get("page_preview_url"),
                }
            )

        objectives = list((template_snapshot or {}).get("planner", {}).get("objectives") or [])
        objective_scores = []
        for objective in objectives:
            objective_id = str(objective["id"])
            required_evidence = str(
                objective.get("required_evidence") or "document_and_answer"
            )
            evidence_items = objective_evidence.get(objective_id, [])
            eligible_evidence = [
                item
                for item in evidence_items
                if (
                    required_evidence not in {"answer", "document_and_answer"}
                    or bool(item.get("answer_quote"))
                )
                and (
                    required_evidence not in {"document", "document_and_answer"}
                    or bool(item.get("source_excerpt"))
                )
            ]
            values = [float(item["score"]) for item in eligible_evidence]
            objective_scores.append(
                {
                    "id": objective_id,
                    "title": localized_text(
                        objective.get("title"), language, objective_id
                    ),
                    "weight": float(objective.get("weight", 0.0)),
                    "score": _average(values) if values else None,
                    "evidence_count": len(eligible_evidence),
                    "evidence": evidence_items,
                    "status": (
                        "assessed"
                        if values
                        else ("evidence_incomplete" if evidence_items else "not_assessed")
                    ),
                    "rubric": {
                        "version": "objective-rubric-v1",
                        "required_evidence": required_evidence,
                        "question_aggregate": "mean",
                        "dimension_weights": {
                            dimension_id: float(contract.get("weight", 0.0))
                            for dimension_id, contract in {
                                str(item["id"]): item
                                for item in assessment_contract.get("dimensions")
                                or []
                            }.items()
                        },
                    },
                }
            )

        dimension_contracts = {
            str(item["id"]): item
            for item in assessment_contract.get("dimensions") or []
        }
        dimension_scores = [
            {
                "id": dimension_id,
                "title": localized_text(
                    contract.get("title"), language, dimension_id
                ),
                "weight": float(contract.get("weight", 0.0)),
                "score": _average(dimension_values.get(dimension_id, [])),
                "evidence_count": len(dimension_evidence.get(dimension_id, [])),
                "evidence": dimension_evidence.get(dimension_id, []),
            }
            for dimension_id, contract in dimension_contracts.items()
        ]

        if objective_scores and any(item["score"] is not None for item in objective_scores):
            computed_overall = _weighted_average(
                [
                    (float(item["score"]), float(item["weight"]))
                    for item in objective_scores
                    if item["score"] is not None
                ]
            )
            overall_basis = "objective_weighted"
        else:
            computed_overall = _average(selected_scores)
            overall_basis = "question_average"
        show_total = bool(report_contract.get("show_total_score", True)) and (
            assessment_contract.get("aggregate") != "no_total"
        )
        overall = computed_overall if show_total else None
        risk_level = (
            "not_scored"
            if overall is None
            else ("high" if overall < 2.5 else ("medium" if overall < 3.7 else "low"))
        )

        knowledge_map, weakness_map, improvement_path = self._knowledge_sections(
            knowledge_states or []
        )
        priority_weaknesses = list(
            dict.fromkeys(
                item["statement"]
                for item in weakness_evidence
                if item["statement"] and float(item["confidence"]) >= 0.5
            )
        )[:8]
        disclaimer_id = str(
            report_contract.get(
                "required_disclaimer", "practice_not_formal_decision"
            )
        )
        identity = (template_snapshot or {}).get("identity") or {}
        assessment_summary = {
            "independent_average": _average(independent_scores),
            "assisted_average": _average(assisted_scores),
            "average_learning_gain": _average(
                [float(item["learning_gain"]) for item in trajectories]
            ),
        }
        if template_snapshot:
            assessment_summary["selected_average"] = _average(selected_scores)
        score_policy_payload: dict[str, Any] | str
        if template_snapshot:
            score_policy_payload = {
                "assisted_performance": assisted_performance,
                "aggregate": assessment_contract.get(
                    "aggregate", "weighted_dimensions"
                ),
                "overall_basis": overall_basis,
                "blend_weights": (
                    ASSISTED_BLEND
                    if assisted_performance == "blend_with_independent"
                    else None
                ),
            }
        else:
            score_policy_payload = (
                "teaching-70-independent-30-assisted-v1"
                if mode == "teaching"
                else "independent-main-answer-v1"
            )
        report = {
            "report_version": self.version if template_snapshot else "assessment-report-v2",
            "title": blueprint.get("title", "AI 答辩报告"),
            "mode": mode,
            "score_policy": score_policy_payload,
            "overall_score": overall,
            "computed_overall_score": computed_overall,
            "show_total_score": show_total,
            "max_score": float(
                (assessment_contract.get("scale") or {}).get("maximum", 5.0)
            ),
            "risk_level": risk_level,
            "questions_answered": len(trajectories),
            "evaluated_turns": len(evaluations),
            "assessment_summary": assessment_summary,
            "question_trajectories": trajectories,
            "objective_scores": objective_scores,
            "dimension_scores": dimension_scores,
            "dimension_summary": {
                item["id"]: item["score"] for item in dimension_scores
            },
            "strengths": list(dict.fromkeys(strengths))[:5],
            "priority_weaknesses": priority_weaknesses,
            "weakness_evidence": weakness_evidence,
            "evidence": evidence,
            "mastery_state": mastery_state,
            "knowledge_map": knowledge_map,
            "weakness_map": weakness_map,
            "improvement_path": improvement_path,
            "recommended_actions": [
                "针对优先薄弱点，重新组织一段不超过两分钟的独立回答。",
                "为每个主要结论补充一个直接证据、一个边界条件和一个反例。",
                "复测时优先使用反事实、泛化与局限类问题，而不是重复定义题。",
            ],
            "disclaimer_id": disclaimer_id,
            "disclaimer": disclaimer(disclaimer_id, language),
            "template": {
                "slug": identity.get("slug"),
                "version": identity.get("version"),
                "title": localized_text(identity.get("title"), language),
                "fingerprint": template_fingerprint,
            }
            if template_snapshot
            else None,
        }
        section_order = list(report_contract.get("sections") or [])
        section_payloads = self._section_payloads(report)
        report["section_order"] = section_order
        report["sections"] = [
            {"id": section_id, "data": section_payloads[section_id]}
            for section_id in section_order
        ]
        return report
