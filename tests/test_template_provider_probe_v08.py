from __future__ import annotations

from ai_examiner.agents.base import AgentContext
from ai_examiner.agents.planner import SessionPlanner
from ai_examiner.config import Settings
from ai_examiner.providers.base import ModelProvider, ProviderResult
from ai_examiner.template_engine.compiler import TemplateCompiler
from ai_examiner.template_engine.evaluation import latest_builtin_sources
from ai_examiner.template_provider_probe_cli import (
    TEMPLATE_PROVIDER_PROBE_VERSION,
    run_provider_probe,
)


class RepairingPlannerProvider(ModelProvider):
    name = "repair-test"
    model = "repair-test-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.last_contract = {}

    def complete_json(self, *, agent, instructions, payload, schema_hint):
        self.calls += 1
        self.last_contract = payload["scenario_planning_contract"]
        allowed = payload["scenario_planning_contract"]["allowed_question_types"]
        objectives = payload["scenario_planning_contract"]["objectives"]
        question_type = "reasoning" if self.calls == 1 else allowed[0]
        return ProviderResult(
            provider=self.name,
            model=self.model,
            data={
                "title": "课程口试",
                "summary": "检查概念理解。",
                "core_contributions": ["概念"],
                "assumptions": ["材料完整"],
                "risks": ["样本较少"],
                "questions": [
                    {
                        "id": "Q1",
                        "text": "请解释核心概念。",
                        "type": question_type,
                        "difficulty": 2,
                        "objective_ids": [objectives[0]["id"]],
                        "expected_points": ["概念定义"],
                        "source_excerpt": "核心概念",
                        "source_page": 1,
                        "followups": ["请举例。"],
                        "knowledge_units": [],
                    }
                ],
            },
        )

    def complete_text(self, *, agent, instructions, payload):
        return ProviderResult(provider=self.name, model=self.model, data="")


def test_planner_retries_once_when_provider_violates_template_contract():
    source = latest_builtin_sources()["education.course_oral"]
    contract = TemplateCompiler().compile(source).compiled
    provider = RepairingPlannerProvider()

    blueprint = SessionPlanner(AgentContext(provider=provider)).plan(
        document_text="核心概念及其应用。",
        filename="course.md",
        language="zh-CN",
        template_contract=contract,
    )

    assert provider.calls == 2
    assert provider.last_contract["identity"]["slug"] == "education.course_oral"
    assert provider.last_contract["presentation"]["role_id"]
    assert provider.last_contract["presentation"]["role_behavior"]
    assert provider.last_contract["presentation"]["style_behavior"]
    assert provider.last_contract["assistance"]["mode"]
    assert provider.last_contract["assessment"]["dimensions"]
    assert provider.last_contract["report"]["sections"]
    assert blueprint["questions"][0]["type"] in contract["question_selection"][
        "allowed_types"
    ]


def test_planner_retries_stacked_questions_until_single_issue():
    class StackedQuestionRepairProvider(RepairingPlannerProvider):
        def complete_json(self, **kwargs):
            result = super().complete_json(**kwargs)
            if self.calls < 3:
                result.data["questions"][0]["text"] = (
                    "请说明核心概念是什么？它为什么重要？"
                )
            return result

    source = latest_builtin_sources()["education.course_oral"]
    contract = TemplateCompiler().compile(source).compiled
    provider = StackedQuestionRepairProvider()

    blueprint = SessionPlanner(AgentContext(provider=provider)).plan(
        document_text="核心概念及其应用。",
        filename="course.md",
        language="zh-CN",
        template_contract=contract,
    )

    assert provider.calls == 3
    text = blueprint["questions"][0]["text"]
    assert text.count("?") + text.count("？") <= 1


def test_single_judgment_question_does_not_treat_background_nouns_as_requests():
    question = (
        "作为评审人，基于材料中“研究设计依赖样本独立性，并计划使用"
        "对照实验”这一前提，您是否认为该方案的方法基础足以支持其比较结论？"
    )

    assert SessionPlanner._has_stacked_request(question) is False


def test_quoted_customer_question_is_context_not_a_second_examiner_request():
    followup = (
        "如果客户追问“为什么不能支持更大的文件？”，您会如何基于产品"
        "设计逻辑简要解释，而不透露未公开的技术细节？"
    )

    assert SessionPlanner._has_stacked_request(followup) is False


def test_two_english_interrogative_tasks_are_stacked():
    question = (
        "Who will own the first concrete step to contain the regression, "
        "and what will that step be?"
    )

    assert SessionPlanner._has_stacked_request(question) is True


def test_planner_repairs_semantically_stacked_main_question_and_followup():
    class SemanticStackRepairProvider(RepairingPlannerProvider):
        def complete_json(self, **kwargs):
            result = super().complete_json(**kwargs)
            if self.calls == 1:
                result.data["questions"][0]["text"] = (
                    "请说明核心依据，并据此判断方案是否成立？"
                )
            elif self.calls == 2:
                result.data["questions"][0]["followups"] = [
                    "请选择一个替代方案，并解释原因？"
                ]
            else:
                result.data["questions"][0]["text"] = "请说明核心依据？"
                result.data["questions"][0]["followups"] = ["哪项证据最关键？"]
            return result

    source = latest_builtin_sources()["education.course_oral"]
    contract = TemplateCompiler().compile(source).compiled
    provider = SemanticStackRepairProvider()

    blueprint = SessionPlanner(AgentContext(provider=provider)).plan(
        document_text="核心概念及其应用。",
        filename="course.md",
        language="zh-CN",
        template_contract=contract,
    )

    assert provider.calls == 3
    assert blueprint["questions"][0]["text"] == "请说明核心依据？"
    assert blueprint["questions"][0]["followups"] == ["哪项证据最关键？"]


def test_stacked_request_detection_ignores_declarative_context():
    assert SessionPlanner._has_stacked_request(
        "材料说明现象并指出限制。请判断结论是否成立？"
    ) is False
    assert SessionPlanner._has_stacked_request(
        "材料说明论文提出了新流程，但差异只在附录中说明；"
        "你应如何判断这项差异论证的证据强度？"
    ) is False
    assert SessionPlanner._has_stacked_request(
        "Please identify the constraint and explain its consequence?"
    ) is True
    assert SessionPlanner._has_stacked_request(
        "请说明证据如何支撑价值，并明确结论何时不成立？"
    ) is True


def test_provider_probe_uses_real_planner_path_without_claiming_relevance():
    report = run_provider_probe(
        settings=Settings(
            model_provider="mock",
            golden_default_profiles="mock:heuristic-v2",
            benchmark_default_profiles="mock:heuristic-v2",
        ),
        profiles=["mock:heuristic-v2"],
        template_slugs=[
            "academic.thesis_defense",
            "education.course_oral",
            "engineering.technical_interview",
        ],
        document_text=(
            "The system compares adaptive and fixed question selection. "
            "The evaluation reports accuracy, limitations, and transfer risk."
        ),
        filename="probe.md",
        language="en",
    )

    assert report["probe_version"] == TEMPLATE_PROVIDER_PROBE_VERSION
    assert report["scope"] == (
        "provider_contract_probe_not_scenario_relevance_judging"
    )
    assert report["status"] == "passed"
    assert report["sample_counts"] == {
        "profiles_requested": 1,
        "profiles_configured": 1,
        "template_runs": 3,
    }
    assert all(
        item["status"] == "passed"
        for item in report["results"][0]["template_results"]
    )
    assert any("does not measure relevance" in item for item in report["limitations"])


def test_provider_probe_reports_unconfigured_profiles_without_calling_them():
    report = run_provider_probe(
        settings=Settings(model_provider="mock"),
        profiles=["anthropic:claude-sonnet-5"],
        template_slugs=["academic.thesis_defense"],
        document_text="A bounded test document.",
        filename="probe.md",
        language="en",
    )

    assert report["status"] == "failed"
    assert report["sample_counts"]["profiles_configured"] == 0
    assert report["results"][0] == {
        "profile": "anthropic:claude-sonnet-5",
        "status": "not_configured",
        "template_results": [],
    }
