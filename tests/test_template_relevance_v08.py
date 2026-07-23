from __future__ import annotations

import json
import sys

import pytest

from ai_examiner.template_engine.evaluation import evaluate_builtin_templates
from ai_examiner.template_engine.relevance import (
    ANSWER_QUALITIES,
    CASES_PER_TEMPLATE,
    DIFFICULTIES,
    LANGUAGES,
    RELEVANCE_JUDGE_REPORT_VERSION,
    SCORE_DIMENSIONS,
    evaluate_relevance_reports,
    expand_relevance_corpus,
    validate_relevance_corpus,
)
from ai_examiner.template_relevance_cli import (
    run_template_relevance_evaluation,
)


def _scores(value: int) -> dict[str, int]:
    return {dimension: value for dimension in SCORE_DIMENSIONS}


def _passing_report(
    template_slugs: set[str],
    *,
    generator_profile: str = "qwen:qwen-plus",
    judge_profile: str = "openai:gpt-5.4-mini",
) -> dict:
    corpus = expand_relevance_corpus()
    return {
        "report_version": RELEVANCE_JUDGE_REPORT_VERSION,
        "corpus_fingerprint": corpus["fingerprint"],
        "generator_profile": generator_profile,
        "judge_profile": judge_profile,
        "blind_judging": True,
        "generation_path": "session_planner",
        "evaluations": [
            {
                "case_id": case["case_id"],
                "baseline": _scores(3),
                "scenario": _scores(5),
                "grounded": True,
                "single_main_question": True,
                "unsafe_or_prohibited": False,
            }
            for case in corpus["cases"]
            if case["template_slug"] in template_slugs
        ],
    }


def test_frozen_relevance_corpus_is_complete_balanced_and_fingerprinted():
    corpus = expand_relevance_corpus()
    validation = validate_relevance_corpus()

    assert validation["status"] == "passed"
    assert validation["case_count"] == 7 * CASES_PER_TEMPLATE
    assert validation["template_count"] == 7
    assert len(corpus["fingerprint"]) == 64
    assert corpus["fingerprint"] == validation["fingerprint"]
    for counts in validation["counts"].values():
        assert counts["languages"] == {language: 15 for language in LANGUAGES}
        assert counts["difficulties"] == {
            str(difficulty): 10 for difficulty in DIFFICULTIES
        }
        assert counts["answer_qualities"] == {
            quality: 6 for quality in ANSWER_QUALITIES
        }


def test_relevance_gate_requires_cross_provider_blind_judging():
    report = _passing_report(
        {
            "academic.thesis_defense",
            "education.course_oral",
            "engineering.technical_interview",
        }
    )
    report["judge_profile"] = report["generator_profile"]

    result = evaluate_relevance_reports([report])

    assert result["status"] == "held"
    assert result["accepted_reports"] == []
    assert result["rejected_reports"][0]["reason"] == (
        "independent_provider_required"
    )


def test_three_complete_templates_release_relevance_but_not_deployment_gates():
    report = _passing_report(
        {
            "academic.thesis_defense",
            "education.course_oral",
            "engineering.technical_interview",
        }
    )
    reverse_report = _passing_report(
        {
            "academic.thesis_defense",
            "education.course_oral",
            "engineering.technical_interview",
        },
        generator_profile="openai:gpt-5.4-mini",
        judge_profile="qwen:qwen-plus",
    )

    relevance = evaluate_relevance_reports([report, reverse_report])
    overall = evaluate_builtin_templates(
        performance_samples=1,
        relevance_reports=[report, reverse_report],
    )

    assert relevance["status"] == "passed"
    assert relevance["templates_passed"] == 3
    assert all(
        item["unique_cases"] == CASES_PER_TEMPLATE
        for item in relevance["template_results"]
        if item["status"] == "passed"
    )
    held = overall["release_evidence"]["held_gates"]
    assert "scenario_relevance_frozen_corpus" not in held
    assert "scenario_relevance_blind_judging" not in held
    assert "docker_compose_rehearsal" in held
    assert overall["release_evidence"]["status"] == "held"


def test_relevance_cli_exports_corpus_and_enforces_evidence(
    tmp_path,
    monkeypatch,
):
    corpus_path = tmp_path / "corpus.json"
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-examiner-evaluate-template-relevance",
            "--export-corpus",
            str(corpus_path),
            "--output",
            str(output),
        ],
    )
    run_template_relevance_evaluation()

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(corpus["cases"]) == 210
    assert report["corpus"]["status"] == "passed"
    assert report["status"] == "held"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-examiner-evaluate-template-relevance",
            "--output",
            str(output),
            "--require-pass",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        run_template_relevance_evaluation()
    assert exc_info.value.code == 2
