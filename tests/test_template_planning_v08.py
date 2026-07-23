from __future__ import annotations

from ai_examiner.agents.adaptive import AdaptiveQuestionSelector


def _project_document(client):
    project = client.post(
        "/api/projects",
        json={"name": "Template planning integration"},
    ).json()
    material = (
        "This paper defines an evidence-grounded adaptive examiner. "
        "The method separates planning, answer analysis, policy selection, "
        "and assessment. Experiments compare fixed and adaptive policies, "
        "while the limitations include sample size and domain coverage. "
    ) * 20
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={"file": ("planning.txt", material.encode(), "text/plain")},
    ).json()
    return project, document


def test_template_contract_guides_blueprint_taxonomy_coverage_and_difficulty(client):
    project, document = _project_document(client)
    response = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={
            "document_id": document["id"],
            "profile": "mock:heuristic-v2",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    plan = payload["template_plan"]
    assert plan["semantic_version"] == "1.2.0"
    assert plan["fingerprint"].startswith("sha256:")
    assert plan["resolution_source"] == "legacy"
    assert plan["coverage"]["status"] == "met"
    assert plan == payload["data"]["template_plan"]

    allowed = set(plan["allowed_question_types"])
    minimum = plan["difficulty"]["minimum"]
    maximum = plan["difficulty"]["maximum"]
    questions = payload["data"]["questions"]
    assert len(questions) == plan["question_limit"] == 6
    assert all(question["type"] in allowed for question in questions)
    assert all(
        minimum <= question["difficulty"] <= maximum for question in questions
    )
    assert all(question["objective_ids"] for question in questions)
    assert {"contribution", "methodology", "evidence_quality", "limitations"} <= {
        objective_id
        for question in questions
        for objective_id in question["objective_ids"]
    }


def test_blueprint_reports_impossible_coverage_instead_of_hiding_shortfall(client):
    project, document = _project_document(client)
    response = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={
            "document_id": document["id"],
            "profile": "mock:heuristic-v2",
            "template_overrides": {"question_limit": 3},
        },
    )

    assert response.status_code == 201
    plan = response.json()["template_plan"]
    assert plan["question_limit"] == 3
    assert len(response.json()["data"]["questions"]) == 3
    assert plan["coverage"]["status"] == "impossible"
    assert {
        item["objective_id"] for item in plan["coverage"]["unmet"]
    } == {"evidence_quality", "limitations"}


def test_adaptive_selector_prioritizes_required_objective_and_filters_contract():
    selector = AdaptiveQuestionSelector()
    questions = [
        {
            "id": "Q1",
            "type": "motivation",
            "difficulty": 2,
            "objective_ids": ["contribution"],
        },
        {
            "id": "Q2",
            "type": "method",
            "difficulty": 3,
            "objective_ids": ["methodology"],
        },
        {
            "id": "Q3",
            "type": "evidence",
            "difficulty": 4,
            "objective_ids": ["evidence_quality"],
        },
        {
            "id": "Q4",
            "type": "evidence",
            "difficulty": 5,
            "objective_ids": ["evidence_quality"],
        },
        {
            "id": "Q5",
            "type": "risk",
            "difficulty": 3,
            "objective_ids": ["methodology"],
        },
    ]
    units = {
        "contribution": {
            "id": "contribution",
            "code": "ku_contribution",
            "importance": 0.7,
        },
        "methodology": {
            "id": "methodology",
            "code": "ku_methodology",
            "importance": 0.7,
        },
        "evidence": {
            "id": "evidence",
            "code": "ku_evidence",
            "importance": 1.0,
        },
    }
    mappings = {
        "Q1": [{"knowledge_unit_id": "contribution", "weight": 1.0}],
        "Q2": [{"knowledge_unit_id": "methodology", "weight": 1.0}],
        "Q3": [{"knowledge_unit_id": "evidence", "weight": 1.0}],
        "Q4": [{"knowledge_unit_id": "evidence", "weight": 1.0}],
        "Q5": [{"knowledge_unit_id": "methodology", "weight": 1.0}],
    }
    states = {
        "methodology": {
            "mastery": 0.8,
            "confidence": 0.8,
            "misconceptions": [],
        },
        "evidence": {
            "mastery": 0.1,
            "confidence": 0.2,
            "misconceptions": [{"status": "active"}],
        },
    }
    policy = {
        "allowed_types": ["motivation", "method", "evidence"],
        "difficulty": {"minimum": 2, "maximum": 4},
        "coverage": {
            "contribution": {"minimum_questions": 1},
            "methodology": {"minimum_questions": 1},
        },
    }

    result = selector.select(
        questions=questions,
        question_units=mappings,
        states=states,
        units=units,
        asked_question_ids=["Q1"],
        current_question_id="Q1",
        policy_contract=policy,
    )

    assert result.question["id"] == "Q2"
    assert "required_objective_coverage" in result.reason_codes
    assert {item["question_id"] for item in result.candidate_scores} == {
        "Q2",
        "Q3",
    }


def test_adaptive_decision_audits_effective_template_policy(client):
    project, document = _project_document(client)
    blueprint = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={
            "document_id": document["id"],
            "profile": "mock:heuristic-v2",
        },
    ).json()
    session = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "question_strategy": "adaptive",
            "question_limit": 2,
        },
    ).json()

    started = client.post(f"/api/sessions/{session['id']}/start")
    assert started.status_code == 200
    decisions = client.get(
        f"/api/sessions/{session['id']}/adaptive-decisions"
    ).json()
    policy = decisions[0]["policy_config"]
    assert policy["template_fingerprint"] == session["template_fingerprint"]
    assert policy["allowed_types"]
    assert policy["coverage"]
    assert policy["difficulty"] == {
        "initial": 3,
        "minimum": 1,
        "maximum": 5,
        "adaptive": False,
    }
