from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from sqlalchemy import select

from ai_examiner.db import SessionLocal
from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID
from ai_examiner.models import ModelUsageLedger, VoiceSession
from ai_examiner.services.model_governance import (
    ensure_model_policy,
    update_model_policy,
)


def create_project_and_blueprint(client):
    project = client.post("/api/projects", json={"name": "实时语音答辩"}).json()
    material = (
        "本文研究主动提问型人工智能。贡献包括证据化问题生成、状态机控制和自适应追问。"
        "实验比较固定问卷和动态策略，发现动态策略能发现更多概念误区，但仍存在样本量有限的局限。"
    ) * 20
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        files={"file": ("voice-paper.txt", material.encode(), "text/plain")},
    ).json()
    blueprint = client.post(
        f"/api/projects/{project['id']}/blueprints",
        params={"document_id": document["id"]},
    ).json()
    return project, blueprint


def test_voice_config_and_session_lifecycle(client, monkeypatch):
    project, blueprint = create_project_and_blueprint(client)
    config = client.get("/api/voice/config")
    assert config.status_code == 200
    assert config.json()["ready"] is True
    assert "marin" in config.json()["voices"]
    providers = {item["id"]: item for item in config.json()["providers"]}
    assert providers["openai"]["ready"] is True
    assert providers["qwen"]["ready"] is True
    assert providers["qwen"]["model"] == "qwen3-omni-flash-realtime"
    assert providers["qwen"]["voices"][0] == "Cherry"
    assert providers["qwen"]["supports_ptt"] is True
    assert providers["qwen"]["max_dialog_turns"] == 8

    created = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "voice": "marin",
            "vad_eagerness": "medium",
            "question_limit": 4,
            "max_followups": 2,
        },
    )
    assert created.status_code == 201
    voice_id = created.json()["id"]
    assert created.json()["status"] == "ready"
    assert "instructions" not in created.json()["config"]

    async def fake_call(*, sdp, session, settings):
        assert "v=0" in sdp
        assert session.model == settings.realtime_model
        return 200, "v=0\r\na=setup:active\r\n", "application/sdp"

    monkeypatch.setattr("ai_examiner.main.create_realtime_call", fake_call)
    sdp = client.post(
        f"/api/voice/sessions/{voice_id}/sdp",
        content="v=0\r\na=setup:actpass\r\n",
        headers={"Content-Type": "application/sdp"},
    )
    assert sdp.status_code == 200
    assert "a=setup:active" in sdp.text
    with SessionLocal() as db:
        usage = db.scalar(
            select(ModelUsageLedger).where(
                ModelUsageLedger.task_type == "voice"
            )
        )
        assert usage.status == "completed"
        assert usage.actual_provider == "openai"
        assert usage.actual_model == "gpt-realtime-2.1"

    user_event = client.post(
        f"/api/voice/sessions/{voice_id}/events",
        json={"event_type": "transcript", "role": "user", "text": "核心创新是主动追问。"},
    )
    assert user_event.status_code == 201
    assistant_event = client.post(
        f"/api/voice/sessions/{voice_id}/events",
        json={
            "event_type": "transcript",
            "role": "assistant",
            "text": "请解释主动追问如何优于固定问题。",
        },
    )
    assert assistant_event.status_code == 201
    first = client.post(
        f"/api/voice/sessions/{voice_id}/events",
        json={"event_type": "first_response", "latency_ms": 680},
    )
    assert first.status_code == 201

    detail = client.get(f"/api/voice/sessions/{voice_id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["status"] == "connected"
    assert data["metrics"]["user_turns"] == 1
    assert data["metrics"]["assistant_turns"] == 1
    assert data["metrics"]["first_response_ms"] == 680
    assert len(data["events"]) == 3

    completed = client.post(
        f"/api/voice/sessions/{voice_id}/complete",
        json={"reason": "test_completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["metrics"]["completion_reason"] == "test_completed"


def test_voice_rejects_unsupported_voice(client):
    project, blueprint = create_project_and_blueprint(client)
    response = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "voice": "not-a-real-voice",
        },
    )
    assert response.status_code == 400


def test_voice_policy_denial_happens_before_upstream_connection(client):
    project, blueprint = create_project_and_blueprint(client)
    with SessionLocal() as db:
        policy = ensure_model_policy(db, LEGACY_ORGANIZATION_ID)
        update_model_policy(
            db,
            policy,
            values={
                "allowed_profiles_json": [
                    {
                        "provider": "mock",
                        "model_pattern": "heuristic-v2",
                        "tasks": ["*"],
                    }
                ]
            },
            principal_id=None,
        )
        db.commit()

    response = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "provider": "openai",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "model_policy_denied"
    with SessionLocal() as db:
        assert db.scalar(select(VoiceSession)) is None
        denied = db.scalar(
            select(ModelUsageLedger).where(
                ModelUsageLedger.task_type == "voice"
            )
        )
        assert denied.status == "denied"


def test_voice_sdp_reports_upstream_connectivity_failure(client, monkeypatch):
    project, blueprint = create_project_and_blueprint(client)
    created = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "provider": "openai",
        },
    )
    assert created.status_code == 201

    async def unreachable_call(**_kwargs):
        request = httpx.Request(
            "POST",
            "https://api.openai.com/v1/realtime/calls",
        )
        raise httpx.ConnectTimeout("timed out", request=request)

    monkeypatch.setattr("ai_examiner.main.create_realtime_call", unreachable_call)
    response = client.post(
        f"/api/voice/sessions/{created.json()['id']}/sdp",
        content="v=0\r\na=setup:actpass\r\n",
        headers={"Content-Type": "application/sdp"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "realtime_upstream_unreachable"
    with SessionLocal() as db:
        usage = db.scalar(
            select(ModelUsageLedger).where(
                ModelUsageLedger.task_type == "voice"
            )
        )
        assert usage.status == "failed"


def test_adaptive_voice_finalizes_transcript_into_knowledge_events(client):
    project, blueprint = create_project_and_blueprint(client)
    created = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "question_strategy": "adaptive",
            "learner_subject_key": "voice-learner",
        },
    ).json()
    voice_id = created["id"]
    client.post(
        f"/api/voice/sessions/{voice_id}/events",
        json={
            "event_type": "transcript",
            "role": "assistant",
            "text": blueprint["data"]["questions"][0]["text"],
        },
    )
    client.post(
        f"/api/voice/sessions/{voice_id}/events",
        json={
            "event_type": "transcript",
            "role": "user",
            "text": "该结论有实验比较作为证据，但只适用于当前样本，不能证明普遍因果。",
        },
    )
    completed = client.post(
        f"/api/voice/sessions/{voice_id}/complete",
        json={"reason": "adaptive_voice_test"},
    )
    assert completed.status_code == 200
    result = completed.json()
    assert result["metrics"]["cognitive_finalized_turns"] == 1
    knowledge = client.get(
        f"/api/sessions/{result['exam_session_id']}/knowledge-state"
    ).json()
    assert knowledge["evidence_event_count"] >= 1
    history = client.get(
        f"/api/subjects/{result['learner_subject_id']}/learning-history"
    ).json()
    assert any(event["source_type"] == "voice" for event in history["events"])


def test_qwen_realtime_session_includes_safe_client_config(client, monkeypatch):
    project, blueprint = create_project_and_blueprint(client)
    created = client.post(
        "/api/voice/sessions",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "provider": "qwen",
            "voice": "Cherry",
            "vad_eagerness": "high",
        },
    )
    assert created.status_code == 201
    data = created.json()
    assert data["provider"] == "qwen"
    assert data["model"] == "qwen3-omni-flash-realtime"
    assert data["config"]["question_limit"] == 4
    assert data["config"]["max_followups"] == 1
    assert data["client_config"]["type"] == "session.update"
    session_config = data["client_config"]["session"]
    assert session_config["voice"] == "Cherry"
    assert session_config["turn_detection"]["type"] == "server_vad"
    assert session_config["turn_detection"]["silence_duration_ms"] == 450
    assert "dashscope" not in str(data).lower()
    assert "api_key" not in str(data).lower()

    class FakeQwenConnection:
        def __init__(self):
            self.sent = []
            self.config_received = asyncio.Event()
            self.stage = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.stage == 0:
                self.stage = 1
                return json.dumps({"type": "session.created"})
            if self.stage == 1:
                await self.config_received.wait()
                self.stage = 2
                return json.dumps({"type": "session.updated"})
            await asyncio.Future()

        async def send(self, message):
            self.sent.append(json.loads(message))
            self.config_received.set()

    upstream = FakeQwenConnection()
    monkeypatch.setattr("ai_examiner.main.websockets.connect", lambda *_args, **_kwargs: upstream)
    with client.websocket_connect(f"/api/voice/sessions/{data['id']}/qwen-ws") as socket:
        assert socket.receive_json()["type"] == "session.created"
        socket.send_json(data["client_config"])
        assert socket.receive_json()["type"] == "session.updated"
    assert upstream.sent[0]["type"] == "session.update"


def test_qwen_browser_gates_microphone_until_initial_response_finishes():
    app_js = (
        Path(__file__).parents[1] / "src" / "ai_examiner" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert "voiceInputReady: false" in app_js
    assert "!state.voiceInputReady || state.voiceMuted" in app_js
    assert "state.voiceInputReady = false" in app_js
    assert "track.enabled = false" in app_js
    assert 'type === "response.done"' in app_js
    assert "state.voiceInputReady = true" in app_js
    assert "track.enabled = !state.voiceMuted && !state.voicePtt" in app_js
    assert 'const transcript = (data.transcript || "").trim()' in app_js
    assert "state.voiceInitialRequestAt = Date.now()" in app_js
    assert "qwen_initial_response_timeout" in app_js
    assert "responseErrorMessage(body, response.status)" in app_js
