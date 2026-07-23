from __future__ import annotations

import pytest

from ai_examiner.config import Settings
from ai_examiner.providers.base import ModelProvider, ProviderResult
from ai_examiner.template_engine.relevance import evaluate_relevance_reports
from ai_examiner.template_engine.relevance_probe import (
    RELEVANCE_PROBE_VERSION,
    run_relevance_probe,
)


class RelevanceProbeProvider(ModelProvider):
    def __init__(self, profile: str) -> None:
        self.name, self.model = profile.split(":", 1)

    def complete_json(
        self,
        *,
        agent,
        instructions,
        payload,
        schema_hint,
    ):
        if agent == "session_planner":
            contract = payload["scenario_planning_contract"]
            allowed_types = contract["allowed_question_types"]
            objectives = contract["objectives"]
            is_scenario = len(objectives) == 1
            prefix = "场景" if is_scenario else "基线"
            data = {
                "title": f"{prefix}评测",
                "summary": "材料理解评测。",
                "core_contributions": ["概念"],
                "assumptions": ["材料完整"],
                "risks": ["证据有限"],
                "questions": [
                    {
                        "id": "Q1",
                        "text": f"{prefix} examiner question",
                        "type": allowed_types[0],
                        "difficulty": contract["difficulty"]["initial"],
                        "objective_ids": [objectives[0]["id"]],
                        "expected_points": ["关键证据"],
                        "source_excerpt": payload["document_text"].splitlines()[0],
                        "source_page": 1,
                        "followups": ["请继续解释。"],
                        "knowledge_units": [],
                    }
                ],
            }
        elif agent.startswith("template_relevance_generator_"):
            items = []
            for case in payload["cases"]:
                case_id = case["case_id"]
                arm = payload["arm"]
                items.append(
                    {
                        "case_id": case_id,
                        "question": f"{arm} examiner question",
                        "followup": "Follow up on the answer.",
                        "rubric": "Score against the target evidence.",
                        "report_action": "Recommend a concrete next step.",
                        "source_excerpt": case["material"],
                    }
                )
            data = {"items": items}
        elif agent == "template_relevance_blind_judge":
            items = []
            for pair in payload["blind_pairs"]:
                arms = {}
                for arm in ("arm_a", "arm_b"):
                    is_scenario = (
                        pair[arm]["question"].startswith("scenario")
                        or pair[arm]["question"].startswith("场景")
                    )
                    arms[arm] = {
                        "relevance": 5 if is_scenario else 3,
                        "clarity": 5 if is_scenario else 3,
                        "discrimination": 5 if is_scenario else 3,
                        "followup_usefulness": 5 if is_scenario else 3,
                        "rubric_fit": 5 if is_scenario else 3,
                        "report_actionability": 5 if is_scenario else 3,
                        "grounded": True,
                        "single_main_question": True,
                        "unsafe_or_prohibited": False,
                    }
                items.append(
                    {
                        "case_id": pair["case"]["case_id"],
                        **arms,
                    }
                )
            data = {"items": items}
        else:
            raise AssertionError(f"Unexpected agent: {agent}")
        return ProviderResult(
            provider=self.name,
            model=self.model,
            data=data,
            input_tokens=100,
            output_tokens=200,
            latency_ms=50,
        )

    def complete_text(self, *, agent, instructions, payload):
        raise AssertionError("Text completion is not used")


def test_relevance_probe_generates_blinds_and_unblinds_matched_artifacts():
    report = run_relevance_probe(
        settings=Settings(model_provider="mock"),
        generator_profile="qwen:qwen-plus",
        judge_profile="openai:gpt-5.4-mini",
        template_slugs=["education.course_oral"],
        batch_size=5,
        cases_per_template=5,
        provider_factory=RelevanceProbeProvider,
    )
    evidence = evaluate_relevance_reports([report])

    assert report["probe_version"] == RELEVANCE_PROBE_VERSION
    assert report["blind_judging"] is True
    assert len(report["evaluations"]) == 5
    assert len(report["artifacts"]) == 5
    assert report["generation_path"] == "session_planner"
    assert len(report["usage"]) == 11
    assert all(
        item["scenario"]["relevance"] == 5
        and item["baseline"]["relevance"] == 3
        for item in report["evaluations"]
    )
    assert evidence["accepted_reports"][0]["evaluation_count"] == 5
    assert evidence["status"] == "held"
    course_result = next(
        item
        for item in evidence["template_results"]
        if item["template_slug"] == "education.course_oral"
    )
    assert course_result["unique_cases"] == 5


def test_relevance_probe_rejects_same_provider_and_mock_profiles():
    with pytest.raises(ValueError, match="different non-Mock"):
        run_relevance_probe(
            settings=Settings(model_provider="mock"),
            generator_profile="qwen:qwen-plus",
            judge_profile="qwen:qwen-max",
            template_slugs=["education.course_oral"],
            provider_factory=RelevanceProbeProvider,
        )

    with pytest.raises(ValueError, match="different non-Mock"):
        run_relevance_probe(
            settings=Settings(model_provider="mock"),
            generator_profile="mock:heuristic-v2",
            judge_profile="openai:gpt-5.4-mini",
            template_slugs=["education.course_oral"],
            provider_factory=RelevanceProbeProvider,
        )


def test_batched_contract_probe_is_calibration_only():
    report = run_relevance_probe(
        settings=Settings(model_provider="mock"),
        generator_profile="qwen:qwen-plus",
        judge_profile="openai:gpt-5.4-mini",
        template_slugs=["education.course_oral"],
        batch_size=2,
        cases_per_template=2,
        generation_path="batched_contract_probe",
        provider_factory=RelevanceProbeProvider,
    )

    evidence = evaluate_relevance_reports([report])

    assert report["generation_path"] == "batched_contract_probe"
    assert evidence["accepted_reports"] == []
    assert evidence["rejected_reports"][0]["reason"] == (
        "runtime_session_planner_path_required"
    )
