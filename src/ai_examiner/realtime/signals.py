from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RealtimeProvider(StrEnum):
    OPENAI = "openai"
    QWEN = "qwen"
    MOCK = "mock"


class RealtimeTransport(StrEnum):
    WEBRTC = "webrtc"
    WEBSOCKET = "websocket"
    REPLAY = "replay"


class VoiceRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class VoiceSignalType(StrEnum):
    CONNECTION_READY = "connection_ready"
    SPEECH_STARTED = "speech_started"
    SPEECH_STOPPED = "speech_stopped"
    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_FINAL = "transcript_final"
    RESPONSE_STARTED = "response_started"
    AUDIO_STARTED = "audio_started"
    AUDIO_COMPLETED = "audio_completed"
    RESPONSE_COMPLETED = "response_completed"
    RESPONSE_CANCELLED = "response_cancelled"
    PLAYBACK_STOPPED = "playback_stopped"
    PROVIDER_ERROR = "provider_error"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_RESTORED = "connection_restored"
    UNKNOWN = "unknown"


class RealtimeCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: RealtimeProvider
    model: str | None = None
    transport: RealtimeTransport
    semantic_turn_detection: bool = False
    automatic_barge_in: bool = False
    server_output_buffer: bool = False
    output_clear: bool = False
    conversation_truncate: bool = False
    push_to_talk: bool = True
    partial_transcripts: bool = True


class VoiceSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str = Field(min_length=1, max_length=120)
    voice_session_id: str = Field(min_length=1, max_length=120)
    provider: RealtimeProvider
    type: VoiceSignalType
    provider_event_id: str | None = Field(default=None, max_length=200)
    response_id: str | None = Field(default=None, max_length=200)
    item_id: str | None = Field(default=None, max_length=200)
    role: VoiceRole | None = None
    occurred_at_ms: int | None = Field(default=None, ge=0)
    audio_offset_ms: int | None = Field(default=None, ge=0)
    text: str | None = None
    is_final: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    raw_event_type: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
