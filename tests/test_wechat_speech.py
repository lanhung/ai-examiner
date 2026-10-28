import base64
import io
import wave

import httpx
import pytest
from sqlalchemy import select
from test_school_exams import classroom as classroom  # noqa: F401
from test_school_exams import headers, join, publish

from ai_examiner import wechat_speech_api as api
from ai_examiner.config import Settings, get_settings
from ai_examiner.db import SessionLocal
from ai_examiner.models import ExamSession, ModelUsageLedger, Project, SchoolAttempt, Turn
from ai_examiner.providers.base import ProviderResult
from ai_examiner.services import wechat_speech
from ai_examiner.services.model_governance import ensure_model_policy, update_model_policy

ROOT = "/api/v1/wechat/voice"


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 100)
    return buffer.getvalue()


@pytest.fixture
def speech(classroom, client, monkeypatch):
    c = classroom
    monkeypatch.setattr(get_settings(), "wechat_speech_enabled", True)
    monkeypatch.setattr(get_settings(), "model_rate_limit_backend", "memory")
    with SessionLocal() as db:
        policy = ensure_model_policy(db, c["organization"])
        update_model_policy(db, policy, principal_id=c["teacher"], values={
            "allowed_profiles_json": [{"provider": "qwen", "model_pattern": "qwen3-*", "tasks": ["voice"]}],
        })
        db.commit()
    exam = publish(client, c).json()
    attempt = join(client, c, exam["id"]).json()
    path = f"{ROOT}/attempt/{attempt['id']}"
    key = client.get(path + "/context", headers=headers(c, "student")).json()["question_key"]
    calls = []

    def provider(settings, *, operation, content):
        calls.append((operation, content))
        data = {"text": "My recorded answer."} if operation == "asr" else {
            "audio_base64": base64.b64encode(wav_bytes()).decode(), "format": "wav",
        }
        return ProviderResult(data, "qwen", "qwen3-asr-flash" if operation == "asr" else "qwen3-tts-flash")

    monkeypatch.setattr(api, "call_speech", provider)
    monkeypatch.setattr(api, "validate_recording", lambda content: 2.0)
    return c, exam, attempt, path, key, calls


def post_record(client, c, path, key, who="student"):
    return client.post(path + "/transcribe", headers=headers(c, who),
                       data={"question_key": key}, files={"file": ("voice.mp3", b"recording", "audio/mpeg")})


def test_transcript_never_submits_an_answer_and_usage_is_charged(client, speech):
    c, _, attempt, path, key, calls = speech
    response = post_record(client, c, path, key)
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "My recorded answer."
    assert response.json()["question_key"] == key
    assert "no-store" in response.headers["cache-control"]
    assert calls == [("asr", b"recording")]
    with SessionLocal() as db:
        assert db.get(SchoolAttempt, attempt["id"]).answers == []
        ledger = db.scalar(select(ModelUsageLedger).where(ModelUsageLedger.task_type == "voice"))
        assert ledger.status == "completed"
        assert ledger.organization_id == c["organization"]
        assert ledger.actor_principal_id == c["student"]
        assert ledger.estimated_cost_usd == get_settings().wechat_speech_call_budget_usd
        assert ledger.reservation_cost_usd >= ledger.estimated_cost_usd


def test_speech_only_reads_current_question_not_reference_answer(client, speech):
    c, _, _, path, key, calls = speech
    response = client.post(path + "/speech", headers=headers(c, "student"),
                           json={"question_key": key})
    assert response.status_code == 200, response.text
    assert calls == [("tts", "What is the limitation?")]
    assert response.json()["format"] == "wav"
    assert "Hold out" not in response.text
    assert client.post(path + "/speech", headers=headers(c, "student"),
                       json={"question_key": key, "text": "Speak something else"}).status_code == 422
    assert client.post(path + "/speech", headers=headers(c, "student"),
                       json={"question_key": key, "segment": 99}).status_code == 422
    assert len(calls) == 1


def test_auth_ownership_and_stale_question_fail_before_provider(client, speech):
    c, _, attempt, path, key, calls = speech
    assert client.get(path + "/context").status_code == 401
    for who in ("teacher", "stranger"):
        assert post_record(client, c, path, key, who).status_code == 404
    assert post_record(client, c, path, "0" * 64).status_code == 409
    with SessionLocal() as db:
        row = db.get(SchoolAttempt, attempt["id"])
        row.answers = [{"answer": "existing", "position": 0}]
        db.commit()
    assert post_record(client, c, path, key).status_code == 409
    with SessionLocal() as db:
        db.get(SchoolAttempt, attempt["id"]).status = "grading"
        db.commit()
    assert post_record(client, c, path, key).status_code == 409
    assert not calls


def test_governance_denial_and_disabled_speech_do_not_call_provider(client, speech, monkeypatch):
    c, _, _, path, key, calls = speech
    monkeypatch.setattr(get_settings(), "wechat_speech_enabled", False)
    assert post_record(client, c, path, key).status_code == 503
    monkeypatch.setattr(get_settings(), "wechat_speech_enabled", True)
    with SessionLocal() as db:
        policy = ensure_model_policy(db, c["organization"])
        update_model_policy(db, policy, principal_id=c["teacher"], values={"allowed_profiles_json": []})
        db.commit()
    assert post_record(client, c, path, key).status_code == 403
    assert not calls


def test_provider_failure_settles_reservation_without_answer_mutation(client, speech, monkeypatch):
    c, _, attempt, path, key, _ = speech

    def fail(*args, **kwargs):
        raise wechat_speech.SpeechError("服务不可用", 502)

    monkeypatch.setattr(api, "call_speech", fail)
    assert post_record(client, c, path, key).status_code == 502
    with SessionLocal() as db:
        assert db.get(SchoolAttempt, attempt["id"]).answers == []
        ledger = db.scalar(select(ModelUsageLedger).where(ModelUsageLedger.task_type == "voice"))
        assert ledger.status == "failed"
        assert ledger.estimated_cost_usd >= get_settings().wechat_speech_call_budget_usd


def test_preview_speech_uses_isolated_teacher_ownership(client, speech):
    c, exam, _, _, _, calls = speech
    preview = client.post(f"/api/v1/school/teacher/exams/{exam['id']}/preview",
                          headers=headers(c, "teacher")).json()
    path = f"{ROOT}/preview/{preview['id']}"
    result = client.get(path + "/context", headers=headers(c, "teacher"))
    assert result.status_code == 200
    key = result.json()["question_key"]
    assert post_record(client, c, path, key, "teacher").status_code == 200
    assert post_record(client, c, path, key, "student").status_code == 403
    assert len(calls) == 1


def test_personal_session_requires_membership_and_current_assistant_turn(client, speech):
    c, _, _, _, _, _ = speech
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.organization_id == c["organization"]))
        from ai_examiner.models import Blueprint
        blueprint = db.get(Blueprint, c["blueprint"])
        session = ExamSession(project_id=project.id, organization_id=project.organization_id,
                              blueprint_id=blueprint.id, status="active")
        db.add(session)
        db.flush()
        db.add(Turn(session_id=session.id, organization_id=project.organization_id,
                    role="assistant", content="Explain the experiment."))
        db.commit()
        path = f"{ROOT}/session/{session.id}"
    teacher = {**headers(c, "teacher"), "X-AI-Examiner-Organization": c["organization"]}
    key = client.get(path + "/context", headers=teacher).json()["question_key"]
    assert client.post(path + "/speech", headers=teacher, json={"question_key": key}).status_code == 200
    student = {**headers(c, "student"), "X-AI-Examiner-Organization": c["organization"]}
    assert client.get(path + "/context", headers=student).status_code == 404


def test_file_validation_checks_content_size_and_duration(monkeypatch):
    with pytest.raises(wechat_speech.SpeechError):
        wechat_speech.validate_recording(b"not mp3")
    with pytest.raises(wechat_speech.SpeechError) as exc:
        wechat_speech.validate_recording(b"x" * (wechat_speech.MAX_AUDIO_BYTES + 1))
    assert exc.value.status == 413
    from types import SimpleNamespace
    monkeypatch.setattr(wechat_speech, "MP3", lambda _: SimpleNamespace(
        info=SimpleNamespace(length=61, channels=1, sample_rate=16000)))
    assert wechat_speech.validate_recording(b"mp3") == 61
    monkeypatch.setattr(wechat_speech, "MP3", lambda _: SimpleNamespace(
        info=SimpleNamespace(length=120, channels=1, sample_rate=16000)))
    with pytest.raises(wechat_speech.SpeechError):
        wechat_speech.validate_recording(b"mp3")


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/a.wav", "https://evil.example/a.wav",
    "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com.evil.example/a.wav",
    "https://user:pass@dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav",
    "file:///tmp/a.wav", "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com:8443/a.wav",
])
def test_tts_rejects_untrusted_download_locations(url):
    with pytest.raises(wechat_speech.SpeechError):
        wechat_speech.audio_result_url(url)


def test_provider_protocol_and_no_bearer_on_audio_download(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}],
                                             "usage": {"prompt_tokens": 25, "completion_tokens": 2}})
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"audio": {
                "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav?Signature=opaque",
            }}})
        assert "authorization" not in request.headers
        assert request.url.scheme == "https"
        return httpx.Response(200, content=wav_bytes())
    real_client = httpx.Client
    monkeypatch.setattr(wechat_speech.httpx, "Client",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    settings = Settings(_env_file=None, dashscope_api_key="test-key")
    result = wechat_speech.call_speech(settings, operation="asr", content=b"synthetic")
    assert result.data["text"] == "hello"
    assert result.input_tokens == 25
    assert "data:audio/mpeg;base64," in requests[0].content.decode()
    result = wechat_speech.call_speech(settings, operation="tts", content="question")
    assert base64.b64decode(result.data["audio_base64"]) == wav_bytes()
    assert len(requests) == 3


def test_provider_errors_never_echo_keys_or_raw_body(monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="private-secret-key"))
    monkeypatch.setattr(wechat_speech.httpx, "Client",
                        lambda **kwargs: real_client(transport=transport, **kwargs))
    with pytest.raises(wechat_speech.SpeechError) as exc:
        wechat_speech.call_speech(Settings(_env_file=None), operation="asr", content=b"synthetic")
    assert "private-secret" not in str(exc.value)
