from copy import deepcopy
from types import SimpleNamespace

import pytest

from ai_examiner.agents.interviewer import Interviewer
from ai_examiner.agents.language import matches_question_language, resolve_session_language
from ai_examiner.agents.orchestrator import ExamOrchestrator
from ai_examiner.agents.planner import SessionPlanner
from ai_examiner.agents.policy import PolicyController


@pytest.mark.parametrize("text,expected", [
    ("Why did you choose an independent test set?", False),
    ("请说明：What would happen if the test set contained samples used in training?", False),
    ("请说明 LSTM 与 RAG 在这个方案中的作用？", True),
    ("RAG 是什么？", True),
    ("论文提出‘每个知识点最多追问两次’，这个约束如何影响效度？", True),
    ("", False),
])
def test_chinese_question_language(text, expected):
    assert matches_question_language(text, "zh-CN") is expected


@pytest.mark.parametrize("slot", ["text", "followups"])
def test_chinese_title_cannot_hide_english_question_or_followup(slot):
    data = {"title": "论文答辩", "summary": "研究方法。", "questions": [{
        "text": "结论的依据是什么？", "followups": ["请说明局限？"],
        "source_excerpt": "This English source excerpt must remain verbatim.",
    }]}
    assert SessionPlanner._matches_language(data, "zh-CN")
    data["questions"][0][slot] = (
        "What is the evidence?" if slot == "text" else ["What is the limitation?"]
    )
    assert not SessionPlanner._matches_language(data, "zh-CN")


def test_original_english_paper_title_does_not_reject_chinese_questions():
    assert SessionPlanner._matches_language({
        "title": "An Evidence Based Assessment.pdf",
        "questions": [{"text": "请说明研究结论的依据？", "followups": ["局限是什么？"]}],
    }, "zh-CN")


def decide(*, candidates, followups, language="zh-CN", attempts=0, answered=True):
    return PolicyController().decide(
        analysis={"answered": answered, "coverage": 0.2, "followup_candidates": candidates},
        question={"followups": followups}, attempts=attempts,
        config={"language": language, "allow_hints": False}, is_last_question=False,
    )


def test_english_analyzer_candidate_uses_chinese_blueprint_without_model_call():
    decision = decide(candidates=["Why does this matter?"], followups=["为什么这个条件重要？"])
    assert decision["followup"] == "为什么这个条件重要？"
    assert decision["policy_audit"]["followup_source"] == "blueprint"
    assert decision["policy_audit"]["rejected_followup_language_count"] == 1
    displayed = Interviewer().respond(
        decision=decision, analysis={}, question={}, next_question=None,
    )
    session = SimpleNamespace(current_question_attempts=1, turns=[SimpleNamespace(
        role="assistant", analysis={"policy_decision": decision},
    )])
    scored = ExamOrchestrator._analysis_question(session, {"id": "Q1", "text": "主问题？"})
    assert scored["text"] == decision["followup"]
    assert scored["text"] in displayed


def test_both_sources_invalid_use_localized_fallback_without_altering_analysis():
    candidates = ["Explain the mechanism."]
    original = deepcopy(candidates)
    decision = decide(candidates=candidates, followups=["What about the evidence?"], attempts=1)
    assert decision["policy_audit"]["followup_source"] == "localized_fallback"
    assert matches_question_language(decision["followup"], "zh-CN")
    assert candidates == original


def test_valid_candidate_kept_and_followup_limit_unchanged():
    question = "论文提出‘提示不直接给出标准答案’，这对测量效度有什么影响？"
    assert decide(candidates=[question], followups=[])["followup"] == question
    assert decide(candidates=[question], followups=[], attempts=2)["action"] == "MOVE_ON"


def test_english_session_retains_english():
    decision = decide(candidates=["What supports that conclusion?"], followups=[], language="en")
    assert decision["policy_audit"]["followup_source"] == "analyzer"
    displayed = Interviewer().respond(
        decision=decision, analysis={}, question={}, next_question=None, language="en",
    )
    assert displayed == "A follow-up question: What supports that conclusion?"


@pytest.mark.parametrize("config,blueprint_language,project_language,expected", [
    ({"language": "en"}, "zh-CN", "zh-CN", "en"),
    ({}, "zh-CN", "en", "zh-CN"),
    ({}, None, "en", "en"),
    ({}, None, None, "zh-CN"),
])
def test_legacy_session_language_resolution(config, blueprint_language, project_language, expected):
    session = SimpleNamespace(config=config, project=SimpleNamespace(language=project_language))
    blueprint = SimpleNamespace(data={"response_language": blueprint_language})
    assert resolve_session_language(session, blueprint) == expected
