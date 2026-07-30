from __future__ import annotations

import copy
from pathlib import Path

import yaml

from ai_examiner.agents.evaluator import Evaluator
from ai_examiner.agents.reporter import ReportGenerator
from ai_examiner.services.template_assessment import recompute_score
from ai_examiner.template_engine.compiler import TemplateCompiler
from ai_examiner.template_engine.validator import validate_template


def compiled_template() -> dict:
    path = (
        Path(__file__).parents[1]
        / "src"
        / "ai_examiner"
        / "templates"
        / "builtin"
        / "academic.thesis_defense.v1_2.yaml"
    )
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TemplateCompiler().compile(source).compiled


def sample_analysis() -> dict:
    return {
        "correctness": "partially_supported",
        "coverage": 0.6,
        "source_grounding": 0.8,
        "reasoning_quality": 0.4,
        "boundary_awareness": 0.5,
        "confidence": 0.8,
        "missing_points": ["Explain the boundary condition"],
        "errors": [],
        "point_assessments": [
            {
                "point_id": "P1",
                "status": "partial",
                "answer_quote": "The baseline improves under the reported setting.",
                "source_evidence_id": "E1",
                "reason": "The answer does not state the boundary.",
            }
        ],
    }


def test_template_evaluator_recomputes_exact_weighted_score_with_evidence():
    snapshot = compiled_template()
    question = {
        "id": "Q1",
        "text": "What supports the claim?",
        "type": "evidence",
        "objective_ids": ["evidence_quality"],
        "source_excerpt": "Table 2 reports the comparison.",
        "source_page": 4,
        "evidence_asset_ids": ["A1"],
    }
    evaluation = Evaluator().evaluate(
        question=question,
        answer="The baseline improves under the reported setting.",
        analysis=sample_analysis(),
        assessment_policy=snapshot["assessment"],
        language="en",
    )

    assert evaluation["assessment_version"] == "template-assessment-v2-relevance-gate"
    assert evaluation["objective_ids"] == ["evidence_quality"]
    assert evaluation["computed_score"] == recompute_score(evaluation)
    assert evaluation["score"] == round(evaluation["computed_score"], 1)
    assert {
        item["id"] for item in evaluation["dimension_assessments"]
    } == {
        "correctness",
        "completeness",
        "evidence_reasoning",
        "boundary_awareness",
    }
    for item in evaluation["dimension_assessments"]:
        assert item["evidence"]
        assert item["evidence"][0]["answer_quote"]
        assert item["rubric"]["excellent"]
        assert item["rubric"]["acceptable"]
        assert item["rubric"]["insufficient"]


def test_voice_and_interaction_signals_cannot_change_correctness_score():
    snapshot = compiled_template()
    baseline = sample_analysis()
    with_voice_signals = {
        **baseline,
        "speech_duration": 0.1,
        "pause_time": 42,
        "interrupt_count": 9,
        "response_latency": 9999,
        "emotion": "nervous",
        "voice_confidence": 0.01,
    }
    question = {"id": "Q1", "text": "Explain.", "objective_ids": ["methodology"]}
    evaluator = Evaluator()
    first = evaluator.evaluate(
        question=question,
        answer="Same answer.",
        analysis=baseline,
        assessment_policy=snapshot["assessment"],
    )
    second = evaluator.evaluate(
        question=question,
        answer="Same answer.",
        analysis=with_voice_signals,
        assessment_policy=snapshot["assessment"],
    )
    assert first["computed_score"] == second["computed_score"]
    assert first["dimensions"]["correctness"] == second["dimensions"]["correctness"]


def test_report_follows_template_objectives_sections_and_disclaimer():
    snapshot = compiled_template()
    question = {
        "id": "Q1",
        "text": "Explain the contribution.",
        "type": "novelty",
        "objective_ids": ["contribution"],
        "source_excerpt": "The paper states its contribution.",
    }
    evaluation = Evaluator().evaluate(
        question=question,
        answer="The contribution is an evidence-grounded adaptive examiner.",
        analysis=sample_analysis(),
        assessment_policy=snapshot["assessment"],
    )
    report = ReportGenerator().generate(
        blueprint={"title": "Defense", "questions": [question]},
        turns=[
            {
                "id": "T1",
                "role": "user",
                "question_id": "Q1",
                "analysis": {"question_context": "main"},
                "evaluation": evaluation,
            }
        ],
        mastery_state={},
        template_snapshot=snapshot,
        language="en",
        template_fingerprint="sha256:test",
    )

    assert report["report_version"] == "assessment-report-v3"
    assert report["section_order"] == snapshot["report"]["sections"]
    assert [item["id"] for item in report["sections"]] == report["section_order"]
    assert report["disclaimer_id"] == "practice_not_formal_decision"
    assert "sole basis" in report["disclaimer"]
    assert report["template"]["slug"] == "academic.thesis_defense"
    assert report["template"]["version"] == "1.2.0"
    assert report["template"]["fingerprint"] == "sha256:test"
    contribution = next(
        item for item in report["objective_scores"] if item["id"] == "contribution"
    )
    assert contribution["score"] == round(evaluation["computed_score"], 2)
    assert contribution["evidence"][0]["answer_quote"]
    assert report["score_policy"]["overall_basis"] == "objective_weighted"
    assert report["overall_score"] == report["computed_overall_score"]


def test_no_total_report_remains_valid_and_hides_total_score():
    snapshot = compiled_template()
    snapshot["assessment"]["aggregate"] = "no_total"
    snapshot["report"]["show_total_score"] = False
    snapshot["report"]["sections"] = [
        "summary",
        "dimension_scores",
        "evidence",
        "recommended_actions",
    ]
    question = {
        "id": "Q1",
        "text": "Reflect on the limitation.",
        "objective_ids": ["limitations"],
    }
    evaluation = Evaluator().evaluate(
        question=question,
        answer="The conclusion is limited to the evaluated distribution.",
        analysis=sample_analysis(),
        assessment_policy=snapshot["assessment"],
    )
    report = ReportGenerator().generate(
        blueprint={"title": "Coaching", "questions": [question]},
        turns=[
            {
                "id": "T1",
                "role": "user",
                "question_id": "Q1",
                "analysis": {"question_context": "main"},
                "evaluation": evaluation,
            }
        ],
        mastery_state={},
        template_snapshot=snapshot,
    )
    assert report["overall_score"] is None
    assert report["computed_overall_score"] > 0
    assert report["show_total_score"] is False
    assert report["risk_level"] == "not_scored"
    assert [item["id"] for item in report["sections"]] == snapshot["report"]["sections"]


def test_unregistered_assessment_dimension_is_rejected():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "ai_examiner"
        / "templates"
        / "builtin"
        / "academic.thesis_defense.v1_2.yaml"
    )
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    invalid = copy.deepcopy(source)
    invalid["assessment_policy"]["dimensions"][0]["id"] = "charisma"
    result = validate_template(invalid)
    assert result.valid is False
    assert "ASSESSMENT_DIMENSION_UNKNOWN" in {
        issue.code for issue in result.issues
    }
