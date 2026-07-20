from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid5

from .signals import (
    RealtimeCapabilities,
    RealtimeProvider,
    RealtimeTransport,
    VoiceRole,
    VoiceSignal,
    VoiceSignalType,
)

SIGNAL_NAMESPACE = UUID("5b828959-4f62-4dd3-8459-e0a153f7cdee")

_ASSISTANT_PARTIAL_EVENTS = {
    "response.output_audio_transcript.delta",
    "response.audio_transcript.delta",
    "response.output_text.delta",
    "response.text.delta",
}
_ASSISTANT_FINAL_EVENTS = {
    "response.output_audio_transcript.done",
    "response.audio_transcript.done",
    "response.output_text.done",
    "response.text.done",
}
_USER_PARTIAL_EVENTS = {"conversation.item.input_audio_transcription.delta"}
_USER_FINAL_EVENTS = {
    "conversation.item.input_audio_transcription.completed",
    "conversation.item.input_audio_transcription.done",
}
_AUDIO_DELTA_EVENTS = {"response.output_audio.delta", "response.audio.delta"}
_AUDIO_DONE_EVENTS = {"response.output_audio.done", "response.audio.done"}


def capabilities_for(
    provider: RealtimeProvider | str,
    *,
    model: str | None = None,
) -> RealtimeCapabilities:
    provider = RealtimeProvider(provider)
    if provider == RealtimeProvider.OPENAI:
        return RealtimeCapabilities(
            provider=provider,
            model=model,
            transport=RealtimeTransport.WEBRTC,
            semantic_turn_detection=True,
            automatic_barge_in=True,
            server_output_buffer=True,
            output_clear=True,
            conversation_truncate=True,
        )
    if provider == RealtimeProvider.QWEN:
        model_name = (model or "").lower()
        supports_semantic_turn = model_name.startswith("qwen3.5-") or model_name.startswith(
            "qwen-audio-3"
        )
        return RealtimeCapabilities(
            provider=provider,
            model=model,
            transport=RealtimeTransport.WEBSOCKET,
            semantic_turn_detection=supports_semantic_turn,
            automatic_barge_in=True,
            server_output_buffer=False,
            output_clear=False,
            conversation_truncate=False,
        )
    return RealtimeCapabilities(
        provider=provider,
        model=model,
        transport=RealtimeTransport.REPLAY,
        semantic_turn_detection=True,
        automatic_barge_in=True,
        server_output_buffer=True,
        output_clear=True,
        conversation_truncate=True,
    )


class RealtimeEventNormalizer:
    """Normalize one provider event stream without changing runtime behavior."""

    def __init__(
        self,
        provider: RealtimeProvider | str,
        *,
        model: str | None = None,
    ) -> None:
        self.provider = RealtimeProvider(provider)
        self.capabilities = capabilities_for(self.provider, model=model)
        self._seen_provider_event_ids: set[str] = set()
        self._audio_started_responses: set[str] = set()
        self._active_response_id: str | None = None

    def normalize(
        self,
        event: Mapping[str, Any],
        *,
        voice_session_id: str,
        occurred_at_ms: int | None = None,
    ) -> list[VoiceSignal]:
        raw = dict(event)
        raw_type = str(raw.get("type") or "unknown")
        provider_event_id = _string(raw.get("event_id"))
        if provider_event_id:
            dedupe_key = f"{voice_session_id}:{provider_event_id}"
            if dedupe_key in self._seen_provider_event_ids:
                return []
            self._seen_provider_event_ids.add(dedupe_key)

        response_id = _response_id(raw)
        item_id = _item_id(raw)
        specs: list[dict[str, Any]] = []

        if raw_type == "session.created":
            specs.append(_spec(VoiceSignalType.CONNECTION_READY, role=VoiceRole.SYSTEM))
        elif raw_type == "input_audio_buffer.speech_started":
            specs.append(
                _spec(
                    VoiceSignalType.SPEECH_STARTED,
                    role=VoiceRole.USER,
                    audio_offset_ms=_non_negative_int(raw.get("audio_start_ms")),
                )
            )
        elif raw_type == "input_audio_buffer.speech_stopped":
            specs.append(
                _spec(
                    VoiceSignalType.SPEECH_STOPPED,
                    role=VoiceRole.USER,
                    audio_offset_ms=_non_negative_int(raw.get("audio_end_ms")),
                )
            )
        elif raw_type in _USER_PARTIAL_EVENTS:
            specs.append(
                _spec(
                    VoiceSignalType.TRANSCRIPT_PARTIAL,
                    role=VoiceRole.USER,
                    text=_user_partial_text(raw),
                )
            )
        elif raw_type in _USER_FINAL_EVENTS:
            specs.append(
                _spec(
                    VoiceSignalType.TRANSCRIPT_FINAL,
                    role=VoiceRole.USER,
                    text=_text(raw, "transcript", "text"),
                    is_final=True,
                )
            )
        elif raw_type == "response.created":
            self._active_response_id = response_id
            specs.append(_spec(VoiceSignalType.RESPONSE_STARTED, role=VoiceRole.ASSISTANT))
        elif raw_type in _ASSISTANT_PARTIAL_EVENTS:
            specs.append(
                _spec(
                    VoiceSignalType.TRANSCRIPT_PARTIAL,
                    role=VoiceRole.ASSISTANT,
                    text=_text(raw, "delta", "text"),
                )
            )
        elif raw_type in _ASSISTANT_FINAL_EVENTS:
            specs.append(
                _spec(
                    VoiceSignalType.TRANSCRIPT_FINAL,
                    role=VoiceRole.ASSISTANT,
                    text=_text(raw, "transcript", "text"),
                    is_final=True,
                )
            )
        elif raw_type in _AUDIO_DELTA_EVENTS:
            audio_response_id = response_id or self._active_response_id or item_id or "active"
            if audio_response_id not in self._audio_started_responses:
                self._audio_started_responses.add(audio_response_id)
                specs.append(_spec(VoiceSignalType.AUDIO_STARTED, role=VoiceRole.ASSISTANT))
        elif raw_type in _AUDIO_DONE_EVENTS:
            specs.append(_spec(VoiceSignalType.AUDIO_COMPLETED, role=VoiceRole.ASSISTANT))
        elif raw_type == "response.done":
            status, reason = _response_status(raw)
            metadata = {"status": status}
            if reason:
                metadata["cancellation_reason"] = reason
            if status == "cancelled":
                signal_type = VoiceSignalType.RESPONSE_CANCELLED
            elif status == "failed":
                signal_type = VoiceSignalType.PROVIDER_ERROR
            else:
                signal_type = VoiceSignalType.RESPONSE_COMPLETED
            specs.append(_spec(signal_type, role=VoiceRole.ASSISTANT, metadata=metadata))
            self._active_response_id = None
        elif raw_type == "error":
            error = raw.get("error") if isinstance(raw.get("error"), Mapping) else {}
            specs.append(
                _spec(
                    VoiceSignalType.PROVIDER_ERROR,
                    role=VoiceRole.SYSTEM,
                    text=_string(error.get("message")) or _string(raw.get("message")),
                    metadata={"code": error.get("code")},
                )
            )
        else:
            specs.append(
                _spec(
                    VoiceSignalType.UNKNOWN,
                    role=VoiceRole.SYSTEM,
                    metadata={"raw_event": _safe_unknown_event(raw)},
                )
            )

        return [
            VoiceSignal(
                signal_id=_signal_id(
                    self.provider,
                    voice_session_id,
                    provider_event_id,
                    raw,
                    occurred_at_ms,
                    spec["type"],
                    index,
                ),
                voice_session_id=voice_session_id,
                provider=self.provider,
                provider_event_id=provider_event_id,
                response_id=response_id,
                item_id=item_id,
                occurred_at_ms=occurred_at_ms,
                raw_event_type=raw_type,
                **spec,
            )
            for index, spec in enumerate(specs)
        ]


def _spec(signal_type: VoiceSignalType, **values: Any) -> dict[str, Any]:
    return {"type": signal_type, **values}


def _signal_id(
    provider: RealtimeProvider,
    voice_session_id: str,
    provider_event_id: str | None,
    event: Mapping[str, Any],
    occurred_at_ms: int | None,
    signal_type: VoiceSignalType,
    index: int,
) -> str:
    basis = provider_event_id or json.dumps(
        {"event": event, "occurred_at_ms": occurred_at_ms},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    name = f"{provider}:{voice_session_id}:{basis}:{signal_type}:{index}"
    return str(uuid5(SIGNAL_NAMESPACE, name))


def _response_id(event: Mapping[str, Any]) -> str | None:
    direct = _string(event.get("response_id"))
    response = event.get("response")
    if direct:
        return direct
    if isinstance(response, Mapping):
        return _string(response.get("id"))
    return None


def _item_id(event: Mapping[str, Any]) -> str | None:
    direct = _string(event.get("item_id"))
    item = event.get("item")
    if direct:
        return direct
    if isinstance(item, Mapping):
        return _string(item.get("id"))
    return None


def _response_status(event: Mapping[str, Any]) -> tuple[str, str | None]:
    response = event.get("response")
    if not isinstance(response, Mapping):
        return "completed", None
    status = _string(response.get("status")) or "completed"
    details = response.get("status_details")
    reason = _string(details.get("reason")) if isinstance(details, Mapping) else None
    return status, reason


def _user_partial_text(event: Mapping[str, Any]) -> str | None:
    text = _string(event.get("text")) or ""
    stash = _string(event.get("stash")) or ""
    return f"{text}{stash}" or _string(event.get("delta"))


def _text(event: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _string(event.get(key))
        if value is not None:
            return value
    return None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _safe_unknown_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_unknown_value(value, depth=0)
        for key, value in event.items()
        if not _blocked_unknown_key(key) and not isinstance(value, bytes)
    }


def _safe_unknown_value(value: Any, *, depth: int) -> Any:
    if isinstance(value, str):
        return value[:500]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= 2:
        return f"<{type(value).__name__}>"
    if isinstance(value, Mapping):
        return {
            str(key): _safe_unknown_value(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
            if not _blocked_unknown_key(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_unknown_value(item, depth=depth + 1) for item in value[:30]]
    return f"<{type(value).__name__}>"


def _blocked_unknown_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in {"audio", "delta", "instructions"} or any(
        fragment in normalized for fragment in ("api_key", "authorization", "token", "secret")
    )
