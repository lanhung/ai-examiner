from ai_examiner.agents.orchestrator import ExamOrchestrator
from ai_examiner.agents.policy import PolicyController
from ai_examiner.models import ExamSession, Turn


def test_policy_follows_up_on_incomplete_answer():
    policy = PolicyController()
    result = policy.decide(
        analysis={
            "answered": True,
            "coverage": 0.3,
            "errors": [],
            "followup_candidates": ["为什么？"],
        },
        attempts=0,
        question={"followups": ["为什么？"]},
        config={"max_followups_per_question": 2, "allow_hints": True},
        is_last_question=False,
    )
    assert result["action"] == "ASK_FOLLOWUP"
    assert result["followup"] == "为什么？"


def test_policy_ends_on_last_sufficient_answer():
    policy = PolicyController()
    result = policy.decide(
        analysis={"answered": True, "coverage": 0.9, "errors": []},
        attempts=0,
        question={},
        config={"max_followups_per_question": 2},
        is_last_question=True,
    )
    assert result["action"] == "END"


def test_followup_answer_is_analyzed_against_active_followup():
    session = ExamSession(
        project_id="project",
        blueprint_id="blueprint",
        current_question_attempts=1,
    )
    session.turns = [
        Turn(
            session_id="session",
            role="assistant",
            kind="question",
            content="I will follow up: How would you verify the cooldown?",
            analysis={
                "policy_decision": {
                    "action": "ASK_FOLLOWUP",
                    "followup": "How would you verify the cooldown?",
                }
            },
        )
    ]
    active = ExamOrchestrator._analysis_question(
        session,
        {
            "id": "Q1",
            "text": "Why are prompts insufficient?",
            "expected_points": ["determinism", "replayability"],
            "followups": ["How would you verify the cooldown?"],
        },
    )
    assert active["text"] == "How would you verify the cooldown?"
    assert active["question_context"] == "followup"
    assert active["expected_points"] == []
    assert active["parent_question"] == "Why are prompts insufficient?"
