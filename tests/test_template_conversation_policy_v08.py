from __future__ import annotations

import copy

from ai_examiner.agents.policy import PolicyController
from ai_examiner.db import SessionLocal
from ai_examiner.models import VoiceSession
from ai_examiner.services.conversation_policy import (
    effective_conversation_policy,
)
from ai_examiner.templates.builtin import load_builtin_template


def _project_blueprint(client):
    project = client.post(
        "/api/projects",
        json={"name": "Conversation policy integration"},
    ).json()
    material = (
        "The system separates question planning, conversation policy, answer "
        "analysis, and assessment. It evaluates adaptive questioning and "
        "reports evidence limitations. "
    ) * 20
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={"file": ("policy.txt", material.encode(), "text/plain")},
    ).json()
    blueprint = client.post(
        f"/api/projects/{project['id']}/blueprints",
        json={
            "document_id": document["id"],
            "profile": "mock:heuristic-v2",
        },
    ).json()
    return project, blueprint


def test_active_interruption_requires_template_and_user_permission():
    snapshot = {
        "conversation": {
            "allowed_actions": ["MOVE_ON", "END"],
            "max_followups_per_question": 0,
            "assistance": {
                "hints": {"allowed": False, "maximum_per_question": 0},
                "corrections": {"allowed": False, "timing": "never"},
                "answer_disclosure": {"allowed": False},
            },
            "interruption": {
                "enabled": True,
                "level": "normal",
                "user_can_disable": True,
            },
        }
    }

    disabled = effective_conversation_policy(
        snapshot,
        user_allows_active_interruption=False,
    )
    enabled = effective_conversation_policy(
        snapshot,
        user_allows_active_interruption=True,
    )
    snapshot["conversation"]["interruption"]["enabled"] = False
    cannot_broaden = effective_conversation_policy(
        snapshot,
        user_allows_active_interruption=True,
    )

    assert disabled["active_interruption"]["enabled"] is False
    assert enabled["active_interruption"]["enabled"] is True
    assert cannot_broaden["active_interruption"]["enabled"] is False


def test_policy_controller_never_executes_forbidden_hint():
    decision = PolicyController().decide(
        analysis={
            "answered": False,
            "coverage": 0.0,
            "errors": [],
            "followup_candidates": ["What evidence would support the claim?"],
        },
        attempts=0,
        question={"followups": ["What evidence would support the claim?"]},
        config={},
        is_last_question=False,
        policy_contract={
            "allowed_actions": ["ASK_FOLLOWUP", "MOVE_ON", "END"],
            "max_followups_per_question": 1,
            "hints": {"allowed": True},
            "corrections": {"allowed": False},
            "answer_disclosure": {"allowed": False},
            "active_interruption": {"enabled": False},
        },
    )

    assert decision["action"] == "ASK_FOLLOWUP"
    assert decision["action"] in decision["policy_audit"]["allowed_actions"]
    assert decision["policy_audit"]["requested_action"] == "GIVE_HINT"
    assert decision["policy_audit"]["fallback_reason"] == (
        "action_not_allowed:GIVE_HINT"
    )
    assert decision["policy_audit"]["answer_disclosure_allowed"] is False


def test_template_without_terminal_action_fails_validation(client):
    source = copy.deepcopy(
        load_builtin_template("academic.thesis_defense.v1_2.yaml")
    )
    source["conversation_policy"]["allowed_actions"] = ["MOVE_ON"]
    response = client.post(
        "/api/templates",
        json={
            "slug": "local.no_terminal_action",
            "category": "academic",
            "semantic_version": "0.1.0",
            "source": source,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TEMPLATE_VALIDATION_FAILED"


def test_text_session_uses_effective_policy_and_audits_decision(client):
    project, blueprint = _project_blueprint(client)
    session = client.post(
        "/api/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "allow_interruptions": True,
            "question_limit": 1,
        },
    ).json()

    policy = session["config"]["conversation_policy"]
    assert policy["answer_disclosure"]["allowed"] is False
    assert policy["active_interruption"]["declared_enabled"] is False
    assert policy["active_interruption"]["enabled"] is False
    assert session["config"]["allow_interruptions"] is False

    assert client.post(f"/api/sessions/{session['id']}/start").status_code == 200
    answer = client.post(
        f"/api/sessions/{session['id']}/answers",
        json={"answer": "I do not know."},
    )
    assert answer.status_code == 200
    audit = answer.json()["decision"]["policy_audit"]
    assert audit["effective_action"] in audit["allowed_actions"]
    assert audit["answer_disclosure_allowed"] is False


def test_openai_and_qwen_voice_share_conversation_policy_and_instructions(client):
    project, blueprint = _project_blueprint(client)
    common = {
        "project_id": project["id"],
        "blueprint_id": blueprint["id"],
        "question_limit": 4,
        "max_followups": 1,
    }
    openai = client.post(
        "/api/voice/sessions",
        json={**common, "provider": "openai", "voice": "marin"},
    )
    qwen = client.post(
        "/api/voice/sessions",
        json={**common, "provider": "qwen", "voice": "Cherry"},
    )

    assert openai.status_code == qwen.status_code == 201
    openai_policy = openai.json()["config"]["conversation_policy"]
    qwen_policy = qwen.json()["config"]["conversation_policy"]
    assert openai_policy == qwen_policy
    assert openai_policy["active_interruption"]["enabled"] is False
    assert openai_policy["answer_disclosure"]["allowed"] is False

    with SessionLocal() as db:
        voice = db.get(VoiceSession, openai.json()["id"])
        instructions = voice.config["instructions"]
    assert "Never reveal ideal answers or expected answer points." in instructions
    assert "Do not proactively interrupt the learner." in instructions
    assert "The learner may always interrupt examiner audio." in instructions
