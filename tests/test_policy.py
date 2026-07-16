from ai_examiner.agents.policy import PolicyController


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
