from __future__ import annotations

import json
import sys

import pytest

from ai_examiner.template_engine.evaluation import (
    TEMPLATE_EVALUATION_RUNNER_VERSION,
    evaluate_builtin_templates,
)
from ai_examiner.template_eval_cli import run_template_evaluation


def test_deterministic_template_evaluation_reports_all_gates_and_held_evidence():
    report = evaluate_builtin_templates(performance_samples=7)

    assert report["report_version"] == TEMPLATE_EVALUATION_RUNNER_VERSION
    assert report["sample_counts"] == {
        "latest_templates": 7,
        "all_packaged_versions": 9,
        "distinctness_pairs": 21,
        "override_probes": report["sample_counts"]["override_probes"],
        "performance_samples": 7,
    }
    assert report["sample_counts"]["override_probes"] > 0
    assert report["deterministic_gates"] == {
        "status": "passed",
        "template_validation": True,
        "deterministic_recompile": True,
        "platform_invariants": True,
        "cross_template_distinctness": True,
        "override_boundaries": True,
    }
    assert report["distinctness"]["failure_count"] == 0
    assert all(item["passed"] for item in report["distinctness"]["matrix"])
    assert report["overrides"]["failure_count"] == 0
    assert all(item["passed"] for item in report["overrides"]["cases"])
    assert report["performance_ms"]["paid_model_cost_usd"] == 0.0
    assert report["release_evidence"]["status"] == "held"
    assert "real_qwen_provider_sample" in report["release_evidence"]["held_gates"]


def test_evaluation_rejects_unbounded_performance_sample_counts():
    with pytest.raises(ValueError, match="between 1 and 500"):
        evaluate_builtin_templates(performance_samples=0)


def test_real_provider_probe_evidence_releases_only_provider_gates():
    reports = [
        {
            "probe_version": "template-provider-probe-v1",
            "status": "passed",
            "results": [
                {
                    "profile": profile,
                    "status": "passed",
                    "template_results": [{"status": "passed"}] * 3,
                }
            ],
        }
        for profile in ("qwen:qwen-plus", "openai:gpt-5.4-mini")
    ]

    report = evaluate_builtin_templates(
        performance_samples=1,
        provider_probe_reports=reports,
    )

    evidence = report["release_evidence"]
    assert evidence["provider_contract_samples"]["status"] == "passed"
    assert {
        item["provider"]
        for item in evidence["provider_contract_samples"]["accepted_samples"]
    } == {"openai", "qwen"}
    assert "real_qwen_provider_sample" not in evidence["held_gates"]
    assert "independent_real_provider_sample" not in evidence["held_gates"]
    assert evidence["status"] == "held"
    assert "scenario_relevance_frozen_corpus" not in evidence["held_gates"]
    assert "scenario_relevance_blind_judging" in evidence["held_gates"]


def test_template_evaluation_cli_writes_report_and_can_enforce_held_gates(
    tmp_path,
    monkeypatch,
):
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-examiner-evaluate-templates",
            "--output",
            str(output),
            "--performance-samples",
            "3",
        ],
    )
    run_template_evaluation()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["deterministic_gates"]["status"] == "passed"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-examiner-evaluate-templates",
            "--output",
            str(output),
            "--performance-samples",
            "3",
            "--require-release-evidence",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        run_template_evaluation()
    assert exc_info.value.code == 2
