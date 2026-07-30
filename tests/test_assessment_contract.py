from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ai_examiner.agents.analyzer import ANSWER_ANALYZER_VERSION, AnswerAnalyzer
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
        self.last_instructions = ""
        self.last_payload: dict[str, Any] = {}

    def complete_json(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        del agent, schema_hint
        self.calls += 1
        self.last_instructions = instructions
        self.last_payload = payload
        return ProviderResult(data=self.responses.pop(0), provider=self.name, model=self.model)

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
        "error_assessments": [],
        "missing_points": [],
        "point_assessments": [
            {
                "point_id": "P1",
                "status": "fully_covered",
                "answer_quote": "The cognitive engine remains authoritative.",
                "source_evidence_id": "page-1",
                "reason": "Directly covers the expected point.",
                "semantic_match": "equivalent",
                "functional_criterion_satisfied": True,
                "explicit_source_conflict": False,
            }
        ],
        "source_grounding": 1.0,
        "reasoning_quality": 1.0,
        "boundary_awareness": 1.0,
        "question_relevance": 1.0,
        "directly_addresses_question": True,
        "question_relevance_reason": "The response directly answers the active question.",
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
    assert analysis["assessment_version"] == ANSWER_ANALYZER_VERSION
    assert analysis["point_assessments"][0]["alternative_accepted"] is False
    assert analysis["point_assessments"][0]["rubric_issue"] == "none"
    assert analysis["point_assessments"][0]["semantic_match"] == "equivalent"
    assert analysis["point_assessments"][0]["functional_criterion_satisfied"] is True
    assert analysis["point_assessments"][0]["explicit_source_conflict"] is False
    assert evaluation["score"] == 5.0
    assert evaluation["dimensions"]["correctness"] == 5.0


def test_cross_question_duplicate_is_capped_and_requires_followup():
    provider = RecordedAssessmentProvider([_response("supported")])
    analyzer = AnswerAnalyzer(AgentContext(provider=provider))
    repeated = (
        "The adaptive method improves recall from 0.61 to 0.79, but the "
        "experiment uses synthetic learners and therefore has limited generalizability."
    )
    question = {
        "id": "Q2",
        "text": "How would you transfer the method to a real classroom?",
        "expected_points": [
            "Describe a classroom validation design and its operational constraints."
        ],
        "type": "transfer",
    }

    analysis = analyzer.analyze(
        question=question,
        answer=repeated,
        history=[{"role": "user", "question_id": "Q1", "content": repeated}],
    )
    evaluation = Evaluator().evaluate(
        question=question,
        answer=repeated,
        analysis=analysis,
    )

    assert analysis["cross_question_duplicate"] is True
    assert analysis["directly_addresses_question"] is False
    assert analysis["question_relevance"] == 0.35
    assert analysis["coverage"] == 0.5
    assert analysis["correctness"] == "partially_supported"
    assert evaluation["computed_score"] <= 2.25
    assert evaluation["quality_gates"]["score_capped"] is True
    assert evaluation["quality_gates"]["cross_question_duplicate"] is True


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


def test_analyzer_accepts_a_defensible_alternative_and_audits_the_rubric():
    response = _response("supported")
    response["claims"] = ["Grounding runs after analysis and before policy."]
    response["point_assessments"][0].update(
        {
            "status": "covered",
            "answer_quote": "after analysis and before policy",
            "reason": (
                "This is a defensible control point that satisfies the same "
                "grounding objective under the stated failure policy."
            ),
            "alternative_accepted": True,
            "functional_criterion_satisfied": True,
            "explicit_source_conflict": False,
            "semantic_match": "none",
            "rubric_issue": "over_specific",
        }
    )
    response["unverified_claims"] = []
    provider = RecordedAssessmentProvider([response])
    analyzer = AnswerAnalyzer(AgentContext(provider=provider))
    question = {
        "id": "Q-alt",
        "text": "Where would you place the grounding control, and why?",
        "type": "decision",
        "expected_points": ["Place the grounding checker downstream of the Policy Controller."],
        "source_excerpt": "The system requires a grounding control before final evaluation.",
    }

    analysis = analyzer.analyze(
        question=question,
        answer=(
            "I would run grounding after answer analysis and before Policy and "
            "Evaluator. This prevents unsupported claims from steering a decision, "
            "and a failed check routes the turn to clarification."
        ),
        history=[],
    )

    point = analysis["point_assessments"][0]
    assert analysis["correctness"] == "supported"
    assert analysis["coverage"] == 1.0
    assert point["alternative_accepted"] is True
    assert point["rubric_issue"] == "over_specific"
    assert analysis["errors"] == []
    assert provider.last_payload["assessment_contract"] == {
        "semantic_paraphrases_are_valid": True,
        "defensible_alternatives_are_valid": True,
        "semantic_equivalence_requires_full_credit": True,
        "satisfied_alternatives_require_full_credit": True,
        "contradiction_requires_explicit_conflict": True,
        "source_excerpt_may_be_non_exhaustive": True,
    }
    normalized_instructions = " ".join(provider.last_instructions.split())
    assert "functional assessment criteria" in normalized_instructions
    assert "Reserve contradicted for an explicit factual or logical conflict" in (
        normalized_instructions
    )


def test_analyzer_keeps_unverified_claims_separate_from_errors():
    response = _response("partially_supported")
    response["errors"] = []
    response["unverified_claims"] = ["The external benchmark improved by 18%."]
    response["point_assessments"][0].update(
        {
            "status": "partial",
            "semantic_match": "partial",
            "functional_criterion_satisfied": False,
            "explicit_source_conflict": False,
            "alternative_accepted": False,
            "rubric_issue": "unsupported_by_context",
        }
    )
    provider = RecordedAssessmentProvider([response])

    analysis = AnswerAnalyzer(AgentContext(provider=provider)).analyze(
        question={
            "id": "Q-source",
            "text": "What evidence supports the decision?",
            "expected_points": ["Use material evidence."],
            "source_excerpt": "The internal pilot reduced median latency.",
        },
        answer=(
            "The internal pilot reduced median latency. An external benchmark also improved by 18%."
        ),
        history=[],
    )

    assert analysis["errors"] == []
    assert analysis["unverified_claims"] == ["The external benchmark improved by 18%."]
    assert analysis["point_assessments"][0]["rubric_issue"] == ("unsupported_by_context")


@pytest.mark.parametrize(
    ("semantic_match", "alternative_accepted", "functional_criterion_satisfied"),
    [
        ("equivalent", False, True),
        ("none", True, True),
    ],
)
def test_analyzer_reconciles_full_credit_contract(
    semantic_match: str,
    alternative_accepted: bool,
    functional_criterion_satisfied: bool,
):
    response = _response("partially_supported")
    response["point_assessments"][0].update(
        {
            "status": "partial",
            "semantic_match": semantic_match,
            "functional_criterion_satisfied": functional_criterion_satisfied,
            "explicit_source_conflict": False,
            "alternative_accepted": alternative_accepted,
            "rubric_issue": "over_specific" if alternative_accepted else "none",
        }
    )
    provider = RecordedAssessmentProvider([response])

    analysis = AnswerAnalyzer(AgentContext(provider=provider)).analyze(
        question={
            "id": "Q-reconcile",
            "text": "Give a defensible solution.",
            "expected_points": ["Meet the reliability objective."],
        },
        answer="This solution meets the reliability objective under the stated constraints.",
        history=[],
    )

    assert analysis["correctness"] == "supported"
    assert analysis["coverage"] == 1.0
    assert analysis["missing_points"] == []
    assert analysis["contract_reconciled_point_ids"] == ["P1"]


def test_analyzer_never_promotes_an_explicit_contradiction():
    response = _response("unsupported")
    response["errors"] = ["The answer explicitly reverses the source fact."]
    response["error_assessments"] = [
        {
            "error": "The answer explicitly reverses the source fact.",
            "kind": "explicit_fact_conflict",
            "reason": "The supplied source states the opposite.",
        }
    ]
    response["point_assessments"][0].update(
        {
            "status": "contradicted",
            "semantic_match": "equivalent",
            "functional_criterion_satisfied": True,
            "explicit_source_conflict": True,
            "alternative_accepted": True,
            "rubric_issue": "none",
        }
    )
    provider = RecordedAssessmentProvider([response])

    analysis = AnswerAnalyzer(AgentContext(provider=provider)).analyze(
        question={
            "id": "Q-conflict",
            "text": "State the source fact.",
            "expected_points": ["The policy layer cannot override evidence."],
        },
        answer="The policy layer can override evidence.",
        history=[],
    )

    assert analysis["correctness"] == "unsupported"
    assert analysis["coverage"] == 0.0
    assert analysis["point_assessments"][0]["status"] == "contradicted"
    assert analysis["contract_reconciled_point_ids"] == []


def test_rubric_mismatch_is_audited_without_becoming_a_factual_error():
    response = _response("partially_supported")
    response["errors"] = ["The answer uses a different implementation."]
    response["error_assessments"] = [
        {
            "error": "The answer uses a different implementation.",
            "kind": "rubric_mismatch",
            "reason": "The expected point prescribes one of several valid implementations.",
        }
    ]
    response["point_assessments"][0].update(
        {
            "status": "partial",
            "semantic_match": "partial",
            "functional_criterion_satisfied": True,
            "explicit_source_conflict": False,
            "alternative_accepted": True,
            "rubric_issue": "over_specific",
        }
    )

    analysis = AnswerAnalyzer(
        AgentContext(provider=RecordedAssessmentProvider([response]))
    ).analyze(
        question={
            "id": "Q-audit",
            "text": "Choose a reliable implementation and justify it.",
            "expected_points": ["Use implementation A."],
        },
        answer="Implementation B meets the same objective with a clear fallback.",
        history=[],
    )

    assert analysis["correctness"] == "supported"
    assert analysis["coverage"] == 1.0
    assert analysis["errors"] == []
    assert analysis["raw_errors"] == ["The answer uses a different implementation."]
    assert analysis["rubric_audit_notes"] == ["The answer uses a different implementation."]


def test_open_answer_adjudicator_does_not_promote_unsatisfied_alternative():
    response = _response("partially_supported")
    response["point_assessments"][0].update(
        {
            "status": "partial",
            "semantic_match": "partial",
            "functional_criterion_satisfied": False,
            "explicit_source_conflict": False,
            "alternative_accepted": False,
            "rubric_issue": "none",
        }
    )
    adjudication = {
        "decisions": [
            {
                "point_id": "P1",
                "functionally_satisfied": False,
                "defensible": True,
                "explicit_source_conflict": False,
                "reason": (
                    "The answer differs from the expected topology but is a "
                    "defensible way to meet the reliability objective."
                ),
            }
        ]
    }
    provider = RecordedAssessmentProvider([response, adjudication])

    analysis = AnswerAnalyzer(AgentContext(provider=provider)).analyze(
        question={
            "id": "Q-open",
            "text": "Where would you place the reliability control, and why?",
            "type": "decision",
            "expected_points": ["Place it after the policy layer."],
            "source_excerpt": "A reliability control is required before final evaluation.",
        },
        answer="Place it before policy so unsupported claims cannot steer the next action.",
        history=[],
    )

    point = analysis["point_assessments"][0]
    assert provider.calls == 2
    assert analysis["correctness"] == "partially_supported"
    assert analysis["coverage"] == 0.5
    assert point["status"] == "partial"
    assert point["alternative_accepted"] is False
    assert point["open_answer_adjudication"]["defensible"] is True
    assert point["open_answer_adjudication"]["functionally_satisfied"] is False


def test_open_answer_adjudicator_recovers_a_satisfied_defensible_alternative():
    response = _response("partially_supported")
    response["point_assessments"][0].update(
        {
            "status": "partial",
            "semantic_match": "partial",
            "functional_criterion_satisfied": False,
            "explicit_source_conflict": False,
            "alternative_accepted": False,
            "rubric_issue": "none",
        }
    )
    adjudication = {
        "decisions": [
            {
                "point_id": "P1",
                "functionally_satisfied": True,
                "defensible": True,
                "explicit_source_conflict": False,
                "reason": "The alternative fully meets the reliability objective.",
            }
        ]
    }
    provider = RecordedAssessmentProvider([response, adjudication])

    analysis = AnswerAnalyzer(AgentContext(provider=provider)).analyze(
        question={
            "id": "Q-open-valid",
            "text": "Where would you place the reliability control, and why?",
            "type": "decision",
            "expected_points": ["Place it after the policy layer."],
            "source_excerpt": "A reliability control is required before final evaluation.",
        },
        answer=(
            "Place it before policy so unsupported claims cannot steer the next "
            "action, and route failures to clarification."
        ),
        history=[],
    )

    assert analysis["correctness"] == "supported"
    assert analysis["coverage"] == 1.0
    assert analysis["point_assessments"][0]["status"] == "covered"
    assert analysis["point_assessments"][0]["alternative_accepted"] is True


def test_open_answer_adjudicator_does_not_promote_a_vague_answer():
    response = _response("partially_supported")
    response["point_assessments"][0].update(
        {
            "status": "partial",
            "semantic_match": "partial",
            "functional_criterion_satisfied": False,
            "explicit_source_conflict": False,
            "alternative_accepted": False,
            "rubric_issue": "none",
        }
    )
    adjudication = {
        "decisions": [
            {
                "point_id": "P1",
                "functionally_satisfied": False,
                "defensible": False,
                "explicit_source_conflict": False,
                "reason": "No constraint or rationale is supplied.",
            }
        ]
    }
    provider = RecordedAssessmentProvider([response, adjudication])

    analysis = AnswerAnalyzer(AgentContext(provider=provider)).analyze(
        question={
            "id": "Q-vague",
            "text": "Choose a reliability control and justify it.",
            "type": "decision",
            "expected_points": ["Use a control before final evaluation."],
        },
        answer="I would use a better control.",
        history=[],
    )

    assert analysis["correctness"] == "partially_supported"
    assert analysis["coverage"] == 0.5
    assert analysis["point_assessments"][0]["status"] == "partial"


def test_open_answer_adjudication_failure_preserves_initial_assessment():
    class FailingAdjudicationProvider(RecordedAssessmentProvider):
        def complete_json(self, **kwargs):
            if self.calls == 1:
                raise TimeoutError("adjudication timed out")
            return super().complete_json(**kwargs)

    response = _response("partially_supported")
    response["point_assessments"][0].update(
        {
            "status": "partial",
            "semantic_match": "partial",
            "functional_criterion_satisfied": False,
            "explicit_source_conflict": False,
            "alternative_accepted": False,
            "rubric_issue": "none",
        }
    )
    provider = FailingAdjudicationProvider([response])

    analysis = AnswerAnalyzer(AgentContext(provider=provider)).analyze(
        question={
            "id": "Q-timeout",
            "text": "Choose a reliability control and justify it.",
            "type": "decision",
            "expected_points": ["Use a control before final evaluation."],
        },
        answer="I would place a control before policy.",
        history=[],
    )

    assert analysis["correctness"] == "partially_supported"
    assert analysis["coverage"] == 0.5
    assert analysis["open_answer_adjudication"] == {
        "status": "unavailable",
        "error_type": "TimeoutError",
    }


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
