from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ai_examiner.agents.analyzer import AnswerAnalyzer
from ai_examiner.agents.base import AgentContext
from ai_examiner.agents.evaluator import Evaluator
from ai_examiner.agents.planner import SessionPlanner
from ai_examiner.agents.reporter import ReportGenerator
from ai_examiner.assessment import Correctness, correctness_value, normalize_correctness
from ai_examiner.providers.base import ModelProvider, ProviderResult
from ai_examiner.providers.schema_utils import hint_to_json_schema


class RecordedAssessmentProvider(ModelProvider):
    name = "qwen"
    model = "qwen-plus"

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)
        self.calls = 0

    def complete_json(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        del agent, instructions, payload, schema_hint
        self.calls += 1
        return ProviderResult(
            data=self.responses.pop(0), provider=self.name, model=self.model
        )

    def complete_json_with_images(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        image_paths: list[Path],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        del image_paths
        return self.complete_json(
            agent=agent,
            instructions=instructions,
            payload=payload,
            schema_hint=schema_hint,
        )

    def complete_text(
        self, *, agent: str, instructions: str, payload: dict[str, Any]
    ) -> ProviderResult:
        del agent, instructions, payload
        return ProviderResult(data="", provider=self.name, model=self.model)


def _response(correctness: str = "correct") -> dict[str, Any]:
    return {
        "answered": True,
        "correctness": correctness,
        "claims": ["The answer states the authority boundary."],
        "errors": [],
        "missing_points": [],
        "point_assessments": [
            {
                "point_id": "P1",
                "status": "fully_covered",
                "answer_quote": "The cognitive engine remains authoritative.",
                "source_evidence_id": "page-1",
                "reason": "Directly covers the expected point.",
            }
        ],
        "source_grounding": 1.0,
        "reasoning_quality": 1.0,
        "boundary_awareness": 1.0,
        "confidence": 0.98,
        "followup_candidates": [],
    }


def test_correctness_aliases_share_one_numeric_contract():
    assert normalize_correctness("correct") is Correctness.SUPPORTED
    assert normalize_correctness("partially_correct") is Correctness.PARTIALLY_SUPPORTED
    assert correctness_value("correct") == correctness_value("supported") == 1.0
    with pytest.raises(ValueError, match="Unknown correctness label"):
        normalize_correctness("mostly_fine")


def test_pipe_delimited_schema_hint_becomes_enum():
    schema = hint_to_json_schema(
        {"correctness": "supported|partially_supported|unsupported|insufficient"}
    )
    assert schema["properties"]["correctness"]["enum"] == [
        "supported",
        "partially_supported",
        "unsupported",
        "insufficient",
    ]


def test_real_provider_alias_can_receive_full_score():
    provider = RecordedAssessmentProvider([_response("correct")])
    analyzer = AnswerAnalyzer(AgentContext(provider=provider))
    question = {
        "id": "Q1",
        "text": "What owns cognitive authority?",
        "expected_points": ["The cognitive engine remains authoritative."],
        "type": "method",
    }
    analysis = analyzer.analyze(question=question, answer="A complete answer", history=[])
    evaluation = Evaluator().evaluate(
        question=question, answer="A complete answer", analysis=analysis
    )
    assert analysis["raw_correctness"] == "correct"
    assert analysis["correctness"] == "supported"
    assert analysis["coverage"] == 1.0
    assert evaluation["score"] == 5.0
    assert evaluation["dimensions"]["correctness"] == 5.0


def test_invalid_label_gets_one_contract_correction_attempt():
    provider = RecordedAssessmentProvider([_response("mostly_fine"), _response("supported")])
    analyzer = AnswerAnalyzer(AgentContext(provider=provider))
    analysis = analyzer.analyze(
        question={"id": "Q1", "text": "Explain it", "expected_points": ["Point one"]},
        answer="Point one is directly addressed.",
        history=[],
    )
    assert provider.calls == 2
    assert analysis["correctness"] == "supported"


def test_invalid_label_fails_after_one_correction_attempt():
    provider = RecordedAssessmentProvider([_response("mostly_fine"), _response("still_wrong")])
    analyzer = AnswerAnalyzer(AgentContext(provider=provider))
    with pytest.raises(ValueError, match="Unknown correctness label"):
        analyzer.analyze(
            question={"id": "Q1", "text": "Explain it", "expected_points": ["Point one"]},
            answer="Point one is directly addressed.",
            history=[],
        )
    assert provider.calls == 2


def test_report_aggregates_question_trajectories_not_attempts():
    turns = [
        {
            "id": "T1",
            "role": "user",
            "question_id": "Q1",
            "analysis": {"question_context": "main"},
            "evaluation": {
                "score": 2.0,
                "question_type": "method",
                "missing_points": ["Point B"],
                "errors": [],
                "supporting_quote": "Initial answer",
                "confidence": 0.8,
            },
        },
        {
            "id": "T2",
            "role": "user",
            "question_id": "Q1",
            "analysis": {"question_context": "followup"},
            "evaluation": {
                "score": 4.5,
                "question_type": "method",
                "missing_points": [],
                "errors": [],
                "supporting_quote": "Recovered answer",
                "confidence": 0.9,
            },
        },
        {
            "id": "T3",
            "role": "user",
            "question_id": "Q2",
            "analysis": {"question_context": "main"},
            "evaluation": {
                "score": 4.0,
                "question_type": "evidence",
                "missing_points": [],
                "errors": [],
                "supporting_quote": "Independent answer",
                "confidence": 0.9,
            },
        },
    ]
    report = ReportGenerator().generate(
        blueprint={
            "title": "Test",
            "questions": [
                {"id": "Q1", "source_excerpt": "Source one"},
                {"id": "Q2", "source_excerpt": "Source two"},
            ],
        },
        turns=turns,
        mastery_state={},
        mode="defense",
    )
    assert report["questions_answered"] == 2
    assert report["evaluated_turns"] == 3
    assert report["overall_score"] == 3.0
    assert report["assessment_summary"] == {
        "independent_average": 3.0,
        "assisted_average": 4.25,
        "average_learning_gain": 1.25,
    }
    assert report["question_trajectories"][0]["learning_gain"] == 2.5
    assert "Point B" not in report["priority_weaknesses"]


def test_planner_retries_when_qwen_uses_wrong_language():
    english = {
        "title": "English title",
        "summary": "English summary",
        "core_contributions": [],
        "assumptions": [],
        "risks": [],
        "questions": [{"id": "Q1", "text": "Why?", "expected_points": ["Reason"]}],
    }
    chinese = {
        **english,
        "title": "中文标题",
        "summary": "中文摘要",
        "questions": [{"id": "Q1", "text": "为什么？", "expected_points": ["说明原因"]}],
    }
    provider = RecordedAssessmentProvider([english, chinese])
    result = SessionPlanner(AgentContext(provider=provider)).plan(
        document_text="English source material.", filename="paper.md", language="zh-CN"
    )
    assert provider.calls == 2
    assert result["title"] == "中文标题"
    assert result["response_language"] == "zh-CN"
