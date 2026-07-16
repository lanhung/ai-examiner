from __future__ import annotations

from sqlalchemy import func, select

from ai_examiner.agents.adaptive import AdaptiveQuestionSelector, DifficultyController
from ai_examiner.db import SessionLocal
from ai_examiner.models import (
    AdaptiveDecision,
    Blueprint,
    Document,
    ExamSession,
    KnowledgeEvidenceEvent,
    KnowledgeState,
    Project,
    Turn,
)
from ai_examiner.services.cognitive import CognitiveStateService


def _blueprint_data() -> dict:
    return {
        "title": "Adaptive test",
        "questions": [
            {
                "id": "Q1",
                "text": "State the motivation.",
                "type": "motivation",
                "difficulty": 2,
                "expected_points": ["problem", "importance"],
                "followups": ["Why is it important?"],
            },
            {
                "id": "Q2",
                "text": "Explain the evidence boundary.",
                "type": "evidence",
                "difficulty": 3,
                "expected_points": ["claim", "evidence", "boundary"],
                "followups": ["What is not supported?"],
            },
            {
                "id": "Q3",
                "text": "Challenge the evidence with a counterexample.",
                "type": "evidence",
                "difficulty": 4,
                "expected_points": ["counterexample", "failure condition"],
                "followups": ["How would you test it?"],
            },
            {
                "id": "Q4",
                "text": "Describe generalization limits.",
                "type": "generalization",
                "difficulty": 5,
                "expected_points": ["distribution shift", "limit"],
                "followups": ["Which part fails first?"],
            },
        ],
    }


def test_difficulty_controller_is_bounded_and_misconception_aware():
    controller = DifficultyController()
    assert controller.target([]) == 2
    assert controller.target([{"mastery": 0.8, "importance": 1.0, "misconceptions": []}]) == 5
    assert (
        controller.target(
            [
                {
                    "mastery": 0.8,
                    "importance": 1.0,
                    "misconceptions": [{"status": "active"}],
                }
            ]
        )
        == 4
    )


def test_selector_prioritizes_important_active_misconception():
    selector = AdaptiveQuestionSelector()
    questions = _blueprint_data()["questions"]
    units = {
        "motivation": {"id": "motivation", "code": "ku_motivation", "importance": 0.7},
        "evidence": {"id": "evidence", "code": "ku_evidence", "importance": 0.95},
        "generalization": {
            "id": "generalization",
            "code": "ku_generalization",
            "importance": 0.82,
        },
    }
    mappings = {
        "Q1": [{"knowledge_unit_id": "motivation", "weight": 1.0}],
        "Q2": [{"knowledge_unit_id": "evidence", "weight": 1.0}],
        "Q3": [{"knowledge_unit_id": "evidence", "weight": 1.0}],
        "Q4": [{"knowledge_unit_id": "generalization", "weight": 1.0}],
    }
    states = {
        "motivation": {"mastery": 0.85, "confidence": 0.8, "misconceptions": []},
        "evidence": {
            "mastery": 0.3,
            "confidence": 0.7,
            "misconceptions": [{"status": "active"}],
        },
    }
    result = selector.select(
        questions=questions,
        question_units=mappings,
        states=states,
        units=units,
        asked_question_ids=["Q1", "Q2"],
        current_question_id="Q2",
    )
    assert result.question["id"] == "Q3"
    assert "misconception_priority" in result.reason_codes
    assert result.candidate_scores[0]["question_id"] == "Q3"


def test_knowledge_state_events_are_idempotent_and_rebuildable():
    with SessionLocal() as db:
        project = Project(name="Adaptive state")
        db.add(project)
        db.flush()
        document = Document(
            project_id=project.id,
            filename="adaptive.txt",
            content_type="text/plain",
            storage_path="/tmp/adaptive.txt",
            content_text="Adaptive evidence test material.",
            char_count=32,
        )
        db.add(document)
        db.flush()
        blueprint = Blueprint(
            project_id=project.id,
            document_id=document.id,
            data=_blueprint_data(),
            provider="mock",
            model="heuristic-v2",
        )
        db.add(blueprint)
        db.flush()
        session = ExamSession(
            project_id=project.id,
            blueprint_id=blueprint.id,
            question_strategy="adaptive",
            policy_version="adaptive-v1",
        )
        db.add(session)
        db.flush()
        turn = Turn(
            session_id=session.id,
            role="user",
            kind="answer",
            question_id="Q2",
            content="The claim is only supported in the measured setting because the evidence is limited.",
        )
        db.add(turn)
        db.flush()
        service = CognitiveStateService(db)
        service.ensure_blueprint_graph(blueprint)
        analysis = {
            "correctness": "partially_supported",
            "coverage": 0.6,
            "confidence": 0.8,
            "errors": ["Treats correlation as causal evidence"],
        }
        evaluation = {"dimensions": {"evidence_reasoning": 3.5}}
        first = service.record_answer(
            session=session,
            blueprint=blueprint,
            turn=turn,
            question=_blueprint_data()["questions"][1],
            analysis=analysis,
            evaluation=evaluation,
        )
        second = service.record_answer(
            session=session,
            blueprint=blueprint,
            turn=turn,
            question=_blueprint_data()["questions"][1],
            analysis=analysis,
            evaluation=evaluation,
        )
        assert [item.id for item in first] == [item.id for item in second]
        assert db.scalar(select(func.count(KnowledgeEvidenceEvent.id))) == 1
        state_before = db.scalar(select(KnowledgeState))
        mastery_before = state_before.mastery
        confidence_before = state_before.confidence
        contradictory_turn = Turn(
            session_id=session.id,
            role="user",
            kind="answer",
            question_id="Q2",
            content="The result proves universal causality in every setting.",
        )
        db.add(contradictory_turn)
        db.flush()
        service.record_answer(
            session=session,
            blueprint=blueprint,
            turn=contradictory_turn,
            question=_blueprint_data()["questions"][1],
            analysis={
                "correctness": "unsupported",
                "coverage": 0.1,
                "confidence": 0.9,
                "errors": ["Overgeneralizes evidence into universal causality"],
            },
            evaluation={"dimensions": {"evidence_reasoning": 0.5}},
        )
        state_after_contradiction = db.scalar(select(KnowledgeState))
        assert state_after_contradiction.mastery < mastery_before
        assert state_after_contradiction.confidence > confidence_before
        rebuilt = service.rebuild(session)
        state_after = db.scalar(select(KnowledgeState))
        assert len(rebuilt) == 1
        assert state_after.mastery == state_after_contradiction.mastery
        assert state_after.misconceptions[0]["status"] == "active"
        assert session.mastery_state["_knowledge"]


def test_adaptive_session_exposes_state_decisions_and_report(client):
    project = client.post("/api/projects", json={"name": "Adaptive API"}).json()
    material = (
        "This paper studies evidence-grounded adaptive questioning. "
        "It compares fixed and adaptive policies and reports limitations. "
    ) * 20
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={"file": ("adaptive.txt", material.encode(), "text/plain")},
    ).json()
    blueprint = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={"document_id": document["id"], "profile": "mock:heuristic-v2"},
    ).json()
    policy_benchmark = client.post(
        f"/api/blueprints/{blueprint['id']}/policy-benchmark",
        json={"question_limit": 2},
    )
    assert policy_benchmark.status_code == 200
    comparison = policy_benchmark.json()["aggregate"]
    assert (
        comparison["adaptive"]["important_gap_discovery"]
        > comparison["fixed"]["important_gap_discovery"]
    )
    assert comparison["adaptive"]["waste_rate"] < comparison["fixed"]["waste_rate"]
    created = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "question_strategy": "adaptive",
            "learner_subject_key": "adaptive-test-subject",
            "question_limit": 2,
            "max_followups_per_question": 0,
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["question_strategy"] == "adaptive"
    assert payload["learner_subject_id"]
    session_id = payload["id"]
    assert client.post(f"/api/sessions/{session_id}/start").status_code == 200

    answer = (
        "The conclusion is supported because the comparison uses explicit evidence and a baseline, "
        "but it remains limited to the measured distribution and does not prove universal causality."
    )
    first = client.post(f"/api/sessions/{session_id}/answers", json={"answer": answer})
    assert first.status_code == 200
    assert first.json()["completed"] is False
    second = client.post(f"/api/sessions/{session_id}/answers", json={"answer": answer})
    assert second.status_code == 200
    assert second.json()["completed"] is True

    session = client.get(f"/api/sessions/{session_id}").json()
    assert len(session["asked_question_ids"]) == 2
    assert len(set(session["asked_question_ids"])) == 2
    knowledge = client.get(f"/api/sessions/{session_id}/knowledge-state").json()
    assert knowledge["evidence_event_count"] == 2
    assert knowledge["states"]
    decisions = client.get(f"/api/sessions/{session_id}/adaptive-decisions").json()
    assert decisions[0]["action"] == "ASK_NEW"
    assert any(item["candidate_scores"] for item in decisions)
    assert any(item["policy_config"] for item in decisions)
    assert all(state["evidence"] for state in knowledge["states"])
    report = client.get(f"/api/sessions/{session_id}/report").json()
    assert report["knowledge_map"]
    assert "weakness_map" in report
    assert "improvement_path" in report

    rebuilt = client.post(f"/api/sessions/{session_id}/knowledge-state/rebuild")
    assert rebuilt.status_code == 200
    subject_id = payload["learner_subject_id"]
    assert client.get(f"/api/subjects/{subject_id}/knowledge-state").json()["states"]
    assert client.get(f"/api/subjects/{subject_id}/learning-history").json()["events"]

    repeated = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "question_strategy": "adaptive",
            "learner_subject_key": "adaptive-test-subject",
            "question_limit": 1,
            "max_followups_per_question": 0,
        },
    ).json()
    repeated_start = client.post(f"/api/sessions/{repeated['id']}/start").json()
    assert repeated_start["turn"]["question_id"] not in session["asked_question_ids"]
    subject_states = client.get(f"/api/subjects/{subject_id}/knowledge-state").json()["states"]
    assert all("code" in state for state in subject_states)


def test_fixed_session_remains_compatible(client):
    project = client.post("/api/projects", json={"name": "Fixed baseline"}).json()
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={"file": ("fixed.txt", ("fixed baseline evidence " * 30).encode(), "text/plain")},
    ).json()
    blueprint = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={"document_id": document["id"], "profile": "mock:heuristic-v2"},
    ).json()
    created = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "question_limit": 2,
            "max_followups_per_question": 0,
        },
    ).json()
    assert created["question_strategy"] == "fixed"
    started = client.post(f"/api/sessions/{created['id']}/start").json()
    assert started["turn"]["question_id"] == "Q1"
    client.post(
        f"/api/sessions/{created['id']}/answers",
        json={"answer": "This is supported because evidence and scope are explicitly explained."},
    )
    session = client.get(f"/api/sessions/{created['id']}").json()
    assert session["asked_question_ids"] == ["Q1", "Q2"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AdaptiveDecision.id))) >= 2
