from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_examiner.realtime import (
    RealtimeEventNormalizer,
    RealtimeProvider,
    RealtimeTransport,
    VoiceSignal,
    VoiceSignalType,
    capabilities_for,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "realtime"


def load_trace(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def normalize_trace(trace: dict) -> list[VoiceSignal]:
    normalizer = RealtimeEventNormalizer(trace["provider"], model=trace["model"])
    signals = []
    for row in trace["events"]:
        signals.extend(
            normalizer.normalize(
                row["event"],
                voice_session_id=trace["voice_session_id"],
                occurred_at_ms=row["at_ms"],
            )
        )
    return signals


@pytest.mark.parametrize("fixture_name", ["openai_trace.json", "qwen_trace.json"])
def test_recorded_provider_traces_normalize_deterministically(fixture_name):
    trace = load_trace(fixture_name)
    first = normalize_trace(trace)
    second = normalize_trace(trace)

    assert [signal.type for signal in first] == trace["expected_signal_types"]
    assert [signal.signal_id for signal in first] == [signal.signal_id for signal in second]
    assert all(signal.voice_session_id == trace["voice_session_id"] for signal in first)
    assert all(signal.provider.value == trace["provider"] for signal in first)


def test_duplicate_provider_event_id_is_idempotent():
    normalizer = RealtimeEventNormalizer("openai", model="gpt-realtime-2.1")
    event = {
        "event_id": "duplicate-event",
        "type": "input_audio_buffer.speech_started",
        "audio_start_ms": 40,
    }

    assert len(normalizer.normalize(event, voice_session_id="voice-1", occurred_at_ms=50)) == 1
    assert normalizer.normalize(event, voice_session_id="voice-1", occurred_at_ms=60) == []
    assert len(normalizer.normalize(event, voice_session_id="voice-2", occurred_at_ms=60)) == 1


def test_audio_delta_emits_audio_started_once_per_response():
    normalizer = RealtimeEventNormalizer("qwen", model="qwen3-omni-flash-realtime")
    created = normalizer.normalize(
        {
            "event_id": "created",
            "type": "response.created",
            "response": {"id": "response-1"},
        },
        voice_session_id="voice-1",
    )
    first_delta = normalizer.normalize(
        {
            "event_id": "delta-1",
            "type": "response.audio.delta",
            "response_id": "response-1",
            "delta": "AAEC",
        },
        voice_session_id="voice-1",
    )
    second_delta = normalizer.normalize(
        {
            "event_id": "delta-2",
            "type": "response.audio.delta",
            "response_id": "response-1",
            "delta": "AwQF",
        },
        voice_session_id="voice-1",
    )

    assert created[0].type == VoiceSignalType.RESPONSE_STARTED
    assert first_delta[0].type == VoiceSignalType.AUDIO_STARTED
    assert second_delta == []


def test_qwen_cancellation_reason_and_partial_stash_are_preserved():
    signals = normalize_trace(load_trace("qwen_trace.json"))
    user_partial = next(
        signal
        for signal in signals
        if signal.type == VoiceSignalType.TRANSCRIPT_PARTIAL
        and signal.role == "user"
    )
    cancelled = next(
        signal for signal in signals if signal.type == VoiceSignalType.RESPONSE_CANCELLED
    )

    assert user_partial.text == "这个结论需要证据"
    assert cancelled.metadata["cancellation_reason"] == "turn_detected"
    assert cancelled.response_id == "resp-q1"


def test_unknown_event_is_auditable_without_copying_audio_payload():
    normalizer = RealtimeEventNormalizer("openai")
    signal = normalizer.normalize(
        {
            "event_id": "unknown-1",
            "type": "provider.future.event",
            "audio": "large-base64-payload",
            "delta": "large-delta",
            "instructions": "private blueprint context",
            "authorization": "Bearer test-secret",
            "useful": {"status": "new"},
        },
        voice_session_id="voice-1",
    )[0]

    assert signal.type == VoiceSignalType.UNKNOWN
    assert signal.raw_event_type == "provider.future.event"
    assert signal.metadata["raw_event"]["useful"] == {"status": "new"}
    assert "audio" not in signal.metadata["raw_event"]
    assert "delta" not in signal.metadata["raw_event"]
    assert "instructions" not in signal.metadata["raw_event"]
    assert "authorization" not in signal.metadata["raw_event"]


def test_capabilities_describe_current_application_transports():
    openai = capabilities_for("openai", model="gpt-realtime-2.1")
    qwen_current = capabilities_for("qwen", model="qwen3-omni-flash-realtime")
    qwen_next = capabilities_for("qwen", model="qwen3.5-omni-flash-realtime")

    assert openai.transport == RealtimeTransport.WEBRTC
    assert openai.server_output_buffer is True
    assert openai.conversation_truncate is True
    assert qwen_current.transport == RealtimeTransport.WEBSOCKET
    assert qwen_current.server_output_buffer is False
    assert qwen_current.semantic_turn_detection is False
    assert qwen_next.semantic_turn_detection is True


def test_voice_signal_is_frozen_and_validated():
    signal = normalize_trace(load_trace("openai_trace.json"))[0]
    with pytest.raises(ValidationError):
        signal.type = VoiceSignalType.PROVIDER_ERROR

    with pytest.raises(ValidationError):
        VoiceSignal(
            signal_id="signal",
            voice_session_id="voice",
            provider=RealtimeProvider.OPENAI,
            type=VoiceSignalType.SPEECH_STARTED,
            occurred_at_ms=-1,
            raw_event_type="input_audio_buffer.speech_started",
        )
