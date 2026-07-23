from __future__ import annotations

import re
from itertools import combinations

from ai_examiner.template_engine.catalog import (
    BUILTIN_TEMPLATE_FILES,
    builtin_template_catalog,
    builtin_template_health,
)
from ai_examiner.template_engine.compiler import TemplateCompiler
from ai_examiner.template_engine.validator import validate_template
from ai_examiner.templates.builtin import load_builtin_template

EXPECTED_SCENARIOS = {
    "academic.thesis_defense",
    "academic.grant_review",
    "education.course_oral",
    "engineering.technical_interview",
    "enterprise.product_knowledge",
    "enterprise.sales_objection",
    "operations.project_review",
}


def latest_scenario_contracts() -> dict[str, dict]:
    contracts: dict[str, tuple[str, dict]] = {}
    compiler = TemplateCompiler()
    for filename in BUILTIN_TEMPLATE_FILES:
        source = load_builtin_template(filename)
        slug = source["template"]["slug"]
        version = source["template"]["version"]
        compiled = compiler.compile(source).compiled
        if slug not in contracts or version > contracts[slug][0]:
            contracts[slug] = (version, compiled)
    return {slug: item[1] for slug, item in contracts.items()}


def behavior_signature(contract: dict) -> dict[str, object]:
    return {
        "objectives": tuple(item["id"] for item in contract["planner"]["objectives"]),
        "question_types": tuple(contract["planner"]["allowed_question_types"]),
        "question_selection": (
            contract["question_selection"]["strategy"],
            contract["question_selection"]["question_limit"],
            tuple(contract["question_selection"]["difficulty"].values()),
        ),
        "assistance": (
            contract["conversation"]["assistance"]["mode"],
            contract["conversation"]["assistance"]["hints"]["allowed"],
            contract["conversation"]["assistance"]["corrections"]["timing"],
            contract["conversation"]["assistance"]["answer_disclosure"]["allowed"],
        ),
        "conversation": (
            contract["conversation"]["max_followups_per_question"],
            tuple(contract["conversation"]["allowed_actions"]),
        ),
        "assessment": (
            tuple(
                (item["id"], item["weight"])
                for item in contract["assessment"]["dimensions"]
            ),
            contract["assessment"]["assisted_performance"],
            contract["assessment"]["aggregate"],
        ),
        "report": (
            tuple(contract["report"]["sections"]),
            contract["report"]["show_total_score"],
            contract["report"]["required_disclaimer"],
        ),
        "presentation": (
            contract["presentation"]["role_id"],
            contract["presentation"]["style_id"],
        ),
        "mode": contract["legacy"]["mode"],
    }


def test_all_reviewed_builtin_scenarios_are_valid_bilingual_and_packaged():
    catalog = builtin_template_catalog()
    health = builtin_template_health()
    assert health["status"] == "ok"
    assert health["template_count"] == 9
    assert health["valid_count"] == 9
    assert health["invalid_count"] == 0

    slugs = {item["slug"] for item in catalog}
    assert slugs == EXPECTED_SCENARIOS
    assert all(item["valid"] for item in catalog)
    assert all(item["fingerprint"].startswith("sha256:") for item in catalog)
    for filename in BUILTIN_TEMPLATE_FILES:
        result = validate_template(load_builtin_template(filename))
        assert result.valid, (filename, result.issues)
        assert result.source is not None
        assert {"zh-CN", "en"} <= set(result.source.template.title.root)
        assert {"zh-CN", "en"} <= set(result.source.template.description.root)


def test_intended_distinct_scenarios_differ_in_at_least_three_runtime_dimensions():
    contracts = latest_scenario_contracts()
    assert set(contracts) == EXPECTED_SCENARIOS
    signatures = {
        slug: behavior_signature(contract) for slug, contract in contracts.items()
    }
    for left, right in combinations(sorted(signatures), 2):
        different = [
            key
            for key in signatures[left]
            if signatures[left][key] != signatures[right][key]
        ]
        assert len(different) >= 3, (left, right, different)


def test_builtin_scenarios_keep_human_review_and_prohibited_use_boundaries():
    forbidden_named_entities = {
        "google",
        "microsoft",
        "amazon",
        "meta",
        "openai",
        "anthropic",
        "harvard",
        "stanford",
    }
    for filename in BUILTIN_TEMPLATE_FILES:
        source = load_builtin_template(filename)
        serialized = str(
            {
                "template": source["template"],
                "presentation": source["presentation_policy"],
            }
        ).lower()
        assert not {
            token
            for token in forbidden_named_entities
            if re.search(rf"\b{re.escape(token)}\b", serialized)
        }, filename
        safety = source["safety_policy"]
        assert safety["human_review_required"] is True
        assert safety["protected_trait_inference"] == "forbidden"
        assert "protected_trait_inference" in safety["prohibited_uses"]
        assert "personality_or_emotion_scoring" in safety["prohibited_uses"]
        assert source["template"]["category"] != "medical"


def test_employment_practice_is_never_an_automatic_decision_template():
    source = load_builtin_template("engineering.technical_interview.v1.yaml")
    assert source["template"]["intended_use"] == "practice"
    assert source["template"]["risk_tier"] == "high"
    assert "automatic_employment_decision" in source["safety_policy"]["prohibited_uses"]
    assert source["report_policy"]["required_disclaimer"] == (
        "training_not_employment_decision"
    )
    assert source["assistance_policy"]["mode"] == "none"
    assert source["assessment_policy"]["assisted_performance"] == "ignore"


def test_coaching_scenarios_can_omit_totals_without_losing_evidence_sections():
    for filename in (
        "enterprise.sales_objection.v1.yaml",
        "operations.project_review.v1.yaml",
    ):
        source = load_builtin_template(filename)
        assert source["assessment_policy"]["aggregate"] == "no_total"
        assert source["report_policy"]["show_total_score"] is False
        assert "objective_scores" in source["report_policy"]["sections"]
        assert "dimension_scores" in source["report_policy"]["sections"]
        assert "evidence" in source["report_policy"]["sections"]
