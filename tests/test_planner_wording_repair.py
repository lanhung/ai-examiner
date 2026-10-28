from copy import deepcopy

import pytest

from ai_examiner.agents.base import AgentContext
from ai_examiner.agents.planner import (
    PLANNER_PROMPT_VERSION,
    PlannerRepairExhausted,
    SessionPlanner,
)
from ai_examiner.providers.base import ModelProvider, ProviderResult
from ai_examiner.template_engine.compiler import TemplateCompiler
from ai_examiner.template_engine.evaluation import latest_builtin_sources


class ScriptedProvider(ModelProvider):
    name = "unit-test"
    model = "recorded"

    def __init__(self, replies):
        self.replies = replies
        self.requests = []

    def complete_json(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        return ProviderResult(provider=self.name, model=self.model,
                              data=deepcopy(self.replies[len(self.requests) - 1]))

    def complete_text(self, **kwargs):
        raise AssertionError("No text fallback")


def fixture_data(slug="academic.thesis_defense"):
    contract = TemplateCompiler().compile(latest_builtin_sources()[slug]).compiled
    question = {
        "id": "Q1", "text": "请说明证据，并解释局限？",
        "type": contract["planner"]["allowed_question_types"][0], "difficulty": 3,
        "objective_ids": [contract["planner"]["objectives"][0]["id"]],
        "expected_points": ["测试集独立", "样本较少", "外推范围有限"],
        "source_excerpt": "独立测试集包含三十个样本。", "source_page": 1,
        "followups": ["为什么选择独立测试集？"],
        "knowledge_units": [{"code": "ku_test", "name": "测试集"}],
    }
    second = {**deepcopy(question), "id": "Q2", "text": "请解释样本的局限？",
              "followups": ["请说明替代方案，并解释原因？"]}
    third = {**deepcopy(question), "id": "Q3", "text": "请说明测试集的用途？"}
    return contract, {"title": "论文答辩", "summary": "检验证据与推断。",
                      "questions": [question, second, third]}


def valid_patch():
    return {"repairs": [
        {"target_id": "q0.text", "text": "请说明结论的依据？",
         "additional_followups": ["请解释局限？"]},
        {"target_id": "q1.followups.0", "text": "请选择替代方案？",
         "additional_followups": ["请解释原因？"]},
    ]}


def run_plan(provider, contract):
    return SessionPlanner(AgentContext(provider=provider)).plan(
        document_text="独立测试集包含三十个样本。", filename="synthetic.txt",
        language="zh-CN", template_contract=contract,
    )


@pytest.mark.parametrize("slug", list(latest_builtin_sources()))
def test_batches_wording_repairs_without_rewriting_evidence_or_rubric(slug):
    contract, original = fixture_data(slug)
    provider = ScriptedProvider([original, valid_patch()])
    result = run_plan(provider, contract)
    assert result["planner_prompt_version"] == PLANNER_PROMPT_VERSION
    assert len(provider.requests) == 2
    payload = provider.requests[1]["payload"]
    assert "document_text" not in payload
    assert "invalid_contract_result" not in payload
    assert [target["question_index"] for target in payload["wording_repair_targets"]] == [0, 1]
    assert payload["scenario_planning_contract"]["identity"]["slug"] == slug
    for before, after in zip(original["questions"], result["questions"], strict=True):
        for key in set(before) - {"text", "followups"}:
            assert after[key] == before[key]
    assert result["questions"][2] == original["questions"][2]
    assert len(result["questions"]) == 3


@pytest.mark.parametrize("mutation", [
    "missing", "duplicate", "unknown", "bool_index", "extra_field", "extra_root",
    "change_valid_text", "change_valid_followup", "bad_list", "too_many",
    "empty", "wrong_language", "stacked", "wrong_type",
])
def test_rejects_invalid_patches_atomically_and_bounds_calls(mutation):
    contract, original = fixture_data()
    patch = valid_patch()
    first, second = patch["repairs"]
    if mutation == "missing":
        patch["repairs"].pop()
    elif mutation == "duplicate":
        second["target_id"] = "q0.text"
    elif mutation == "unknown":
        second["target_id"] = "q999.text"
    elif mutation == "bool_index":
        first["target_id"] = False
    elif mutation == "extra_field":
        first["expected_points"] = ["Injected scoring"]
    elif mutation == "extra_root":
        patch["questions"] = []
    elif mutation == "change_valid_text":
        second["target_id"] = "q1.text"
    elif mutation == "change_valid_followup":
        first["target_id"] = "q0.followups.0"
    elif mutation == "bad_list":
        second["additional_followups"] = "不是列表"
    elif mutation == "too_many":
        second["additional_followups"] = ["为什么？"] * 6
    elif mutation == "empty":
        first["text"] = " "
    elif mutation == "wrong_language":
        first["text"] = "What evidence supports this?"
    elif mutation == "stacked":
        second["additional_followups"] = ["为什么？怎么做？"]
    elif mutation == "wrong_type":
        second["additional_followups"] = [None]
    provider = ScriptedProvider([original, patch, patch, patch])
    with pytest.raises(PlannerRepairExhausted):
        run_plan(provider, contract)
    assert len(provider.requests) == 4
    for request in provider.requests[1:]:
        targets = request["payload"]["wording_repair_targets"]
        assert targets[0]["question"] == original["questions"][0]
        assert targets[1]["question"] == original["questions"][1]
    assert provider.requests[2]["payload"]["previous_repair_error"]


def test_invalid_patch_can_be_retried_without_full_regeneration():
    contract, original = fixture_data()
    provider = ScriptedProvider([original, {"questions": []}, valid_patch()])
    result = run_plan(provider, contract)
    assert len(provider.requests) == 3
    assert result["questions"][0]["text"] == "请说明结论的依据？"
    assert "wording_repair_targets" in provider.requests[2]["payload"]


def test_first_output_retains_full_material_and_question_budget():
    contract, data = fixture_data()
    data["questions"] = [data["questions"][2]]
    provider = ScriptedProvider([data])
    run_plan(provider, contract)
    request = provider.requests[0]
    assert request["payload"]["document_text"] == "独立测试集包含三十个样本。"
    assert request["payload"]["scenario_planning_contract"]["question_limit"] == 6
    assert "Preserve the" in request["instructions"]
    assert "required difficulty and discrimination" in request["instructions"]
    assert provider.requests[0]["agent"] == "session_planner"
    assert "3-5 short" in request["instructions"]
    assert "verbatim quotes" in request["instructions"]


def test_planner_reports_real_stages_without_extra_model_calls():
    contract, original = fixture_data()
    provider = ScriptedProvider([original, valid_patch()])
    stages = []
    result = SessionPlanner(AgentContext(provider=provider)).plan(
        document_text="独立测试集包含三十个样本。", filename="paper.txt",
        language="zh-CN", template_contract=contract, on_stage=stages.append,
    )
    assert stages == ["generating", "repairing_questions_1", "validating"]
    assert result["questions"] and len(provider.requests) == 2


def test_multiple_slots_in_one_question_preserve_indices_and_append_after_replacements():
    contract, original = fixture_data()
    original["questions"][0]["followups"] = ["请选择方案，并解释原因？", "样本量多少？"]
    patch = valid_patch()
    patch["repairs"].insert(0, {
        "target_id": "q0.followups.0", "text": "请选择方案？",
        "additional_followups": ["为何选择该方案？"],
    })
    provider = ScriptedProvider([original, patch])
    result = run_plan(provider, contract)
    assert result["questions"][0]["followups"] == [
        "请选择方案？", "样本量多少？", "为何选择该方案？", "请解释局限？",
    ]


def test_additional_followup_limit_is_per_question_not_per_patch():
    contract, original = fixture_data()
    original["questions"][0]["followups"] = ["请选择方案，并解释原因？"]
    patch = valid_patch()
    patch["repairs"][0]["additional_followups"] = ["为什么？"] * 3
    patch["repairs"].append({
        "target_id": "q0.followups.0", "text": "请选择方案？",
        "additional_followups": ["为什么？"] * 2,
    })
    provider = ScriptedProvider([original, patch, patch, patch])
    with pytest.raises(PlannerRepairExhausted):
        run_plan(provider, contract)
    assert "bound" in provider.requests[-1]["payload"]["previous_repair_error"]


def test_main_question_repair_accepts_no_original_followups():
    contract, original = fixture_data()
    original["questions"][0]["followups"] = None
    provider = ScriptedProvider([original, valid_patch()])
    result = run_plan(provider, contract)
    assert result["questions"][0]["followups"] == ["请解释局限？"]


def test_repair_feedback_includes_rejected_followup_and_precise_slot():
    contract, original = fixture_data()
    bad = valid_patch()
    bad["repairs"][1]["additional_followups"] = ["为什么？怎么做？"]
    provider = ScriptedProvider([original, bad, valid_patch()])
    result = run_plan(provider, contract)
    payload = provider.requests[2]["payload"]
    assert "q1.followups.0.additional_followups.0" in payload["previous_repair_error"]
    assert payload["rejected_repair"] == bad
    assert result["questions"][2] == original["questions"][2]


def test_structural_repair_budget_exhaustion_is_explicit():
    contract, original = fixture_data()
    original["questions"][0]["type"] = "unsupported"
    provider = ScriptedProvider([original] * 4)
    with pytest.raises(PlannerRepairExhausted):
        run_plan(provider, contract)
    assert len(provider.requests) == 4


@pytest.mark.parametrize("wording", [
    "这一结果是否足以支持结论？为什么？",
    "材料包含三十个样本。请分析：这一结果能否支持结论？依据是什么？",
    "材料称‘样本是否代表总体？尚待检验’。这一结果可否支持结论？为何？",
])
def test_judgment_and_bare_reason_become_one_reasoning_question(wording):
    normalized = SessionPlanner._normalize_judgment_reason(wording)
    assert normalized != wording
    assert normalized.endswith("你的判断依据是什么？")
    assert "这一结果" in normalized
    assert "支持结论" in normalized
    assert not SessionPlanner._has_stacked_request(normalized)
    assert SessionPlanner._normalize_judgment_reason(normalized) == normalized


@pytest.mark.parametrize("wording", [
    "哪个假设成立？其结果提供什么证据？",
    "结论是否成立？为什么不能排除选择偏差？",
    "请选择方案，并解释原因？",
    "是否成立？如何验证？为什么？",
    "研究问题是‘是否成立？为什么？’",
    "如果样本不足，这是否成立？为什么？",
    "是否成立？",
])
def test_normalization_does_not_drop_distinct_questions_or_quoted_context(wording):
    assert SessionPlanner._normalize_judgment_reason(wording) == wording


def test_reasoning_normalization_avoids_model_repair_preserves_evidence_and_points():
    contract, original = fixture_data()
    question = original["questions"][2]
    question["text"] = "这一结果是否足以支持结论？为什么？"
    question["followups"] = ["样本能否支持外推？依据是什么？"]
    original["questions"] = [question]
    provider = ScriptedProvider([original])
    result = run_plan(provider, contract)
    assert len(provider.requests) == 1
    for key in set(question) - {"text", "followups"}:
        assert result["questions"][0][key] == question[key]


def test_patch_normalization_still_requires_reasoning_and_atomic_validation():
    contract, original = fixture_data()
    patch = valid_patch()
    patch["repairs"][0]["text"] = "这一结果是否足以支持结论？为什么？"
    provider = ScriptedProvider([original, patch])
    result = run_plan(provider, contract)
    assert len(provider.requests) == 2
    assert result["questions"][0]["text"].endswith("你的判断依据是什么？")
