# v0.6 Advanced Conversation Timing Architecture

## 1. Objective

v0.6 turns the realtime voice beta into a measurable oral-examination control
system. The release must improve natural turn-taking without weakening the v0.5
adaptive cognitive engine.

The target is not a visual imitation of another voice product. The target is a
responsive examiner that knows when to listen, wait, speak, stop, redirect and
recover, with every important decision recorded and testable.

## 2. Current v0.5 baseline

The current implementation already provides:

- OpenAI WebRTC speech-to-speech;
- Qwen realtime audio through a proxied WebSocket;
- semantic or server VAD configuration;
- user barge-in and push-to-talk fallback;
- transcript persistence and voice metrics;
- finalized transcript handoff to the v0.5 cognitive engine.

The main gaps are:

- raw provider events drive UI state directly;
- no shared server-side conversation state machine;
- interruptions have a count but usually no structured reason or recovery result;
- unfinished assistant intent is not preserved;
- active AI interruption is mostly a prompt instruction;
- no provider-parity or false-interruption evaluation suite.

## 3. Two-speed control architecture

```text
Browser microphone and playback
        |
        | provider media connection
        v
Provider Realtime Adapter ----------------------+
        | normalized VoiceSignal                |
        v                                       |
Conversation Timing FSM                         | immediate media reflex
        |                                       | cancel / clear / truncate
        +--> Active Interruption Detector       |
        |          | proposal                   |
        |          v                            |
        +--> Deterministic Policy Gate ----------+
        |
        +--> Recovery Planner
        |
        v
Finalized Answer Evidence
        |
        v
v0.5 Analyzer -> Evaluator -> Knowledge State -> Adaptive Selector
```

### 3.1 Media reflex layer

Responsibilities:

- stop assistant audio as soon as genuine user speech begins;
- cancel the in-progress response;
- clear buffered output where the provider supports it;
- reconcile unplayed output with provider conversation history;
- emit timing measurements.

This path must not wait for a policy-model call.

### 3.2 Conversation timing layer

Responsibilities:

- own legal state transitions;
- distinguish a thinking pause from a completed answer;
- enforce one active response at a time;
- control response creation when application gating is enabled;
- start recovery after interruption or reconnect;
- persist normalized events and transition reasons.

### 3.3 Semantic policy layer

Responsibilities:

- classify sustained off-topic speech, repetition, evasion and critical fact errors;
- propose only actions from the finite policy vocabulary;
- attach confidence and transcript evidence;
- never mutate cognitive state or directly send audio commands.

## 4. Canonical state machine

The server owns the canonical state. The browser keeps a projection for immediate
UI feedback.

```text
DISCONNECTED -> CONNECTING -> READY -> LISTENING
                                      |
                                      v
                                USER_SPEAKING
                                  |       |
                     incomplete --+       +-- complete
                                  v       v
                         WAITING_FOR_MORE  ANALYZING_TURN
                                  |       |
                                  +-------+--> AI_SPEAKING
                                                   |
                           user starts speaking ---+--> USER_BARGE_IN
                                                   |        |
                       policy-authorized redirect -+        v
                                                   |   RECOVERING
                                                   |        |
                                                   +--------+--> LISTENING

Any connected state -> PAUSED / ENDING / ERROR
ENDING -> COMPLETED
ERROR -> RECOVERING or DISCONNECTED
```

Canonical states:

| State | Meaning | Allowed output |
|---|---|---|
| `DISCONNECTED` | No provider connection | None |
| `CONNECTING` | Signaling or socket setup | None |
| `READY` | Connected, no examination turn started | Greeting only |
| `LISTENING` | Waiting for user speech | None |
| `USER_SPEAKING` | User audio is active | None |
| `WAITING_FOR_MORE` | Possible thinking pause | Optional nonverbal UI only |
| `ANALYZING_TURN` | Final transcript is being classified | None |
| `AI_SPEAKING` | One assistant response is playing | Current response only |
| `USER_BARGE_IN` | User interrupted assistant | Stop/cancel actions only |
| `AI_INTERRUPTING` | Policy authorized an active redirect | One short redirect only |
| `RECOVERING` | Reconcile unfinished intent and next action | Recovery utterance only |
| `PAUSED` | User paused the session | None |
| `ENDING` | Final transcript and metrics flush | Closing utterance only |
| `COMPLETED` | Session ended | None |
| `ERROR` | Recoverable or terminal failure | Error/retry UI only |

Illegal transitions must be rejected and logged. Duplicate provider events must be
idempotent.

## 5. Normalized provider contract

### 5.1 VoiceSignal

```json
{
  "signal_id": "uuid",
  "voice_session_id": "uuid",
  "provider": "openai",
  "type": "speech_started",
  "provider_event_id": "event-id",
  "response_id": null,
  "item_id": null,
  "occurred_at_ms": 0,
  "audio_offset_ms": null,
  "text": null,
  "is_final": false,
  "confidence": null,
  "raw_event_type": "input_audio_buffer.speech_started"
}
```

Normalized signal types:

```text
connection_ready
speech_started
speech_stopped
transcript_partial
transcript_final
response_started
audio_started
audio_completed
response_completed
response_cancelled
playback_stopped
provider_error
connection_lost
connection_restored
```

### 5.2 RealtimeProviderAdapter

```python
class RealtimeProviderAdapter(Protocol):
    capabilities: RealtimeCapabilities

    def normalize_event(self, event: dict) -> list[VoiceSignal]: ...
    async def cancel_response(self, response_id: str | None) -> None: ...
    async def clear_output(self) -> None: ...
    async def truncate_unplayed(
        self, item_id: str, audio_end_ms: int
    ) -> None: ...
    async def configure_turn_detection(self, config: TurnConfig) -> None: ...
```

Capability flags include:

```text
transport: webrtc | websocket
semantic_turn_detection
automatic_barge_in
server_output_buffer
output_clear
conversation_truncate
push_to_talk
partial_transcripts
```

Policy code must branch on capabilities, not provider names.

## 6. Interruption policy

### 6.1 Reason vocabulary

```text
USER_BARGE_IN
USER_REQUESTED_STOP
OFF_TOPIC_SUSTAINED
REPETITION_LOOP
EVASION_REPEATED
CRITICAL_FACT_ERROR
TIME_BUDGET_EXCEEDED
SAFETY_CRITICAL
NOISE_FALSE_START
PROVIDER_CANCELLED
CONNECTION_LOST
```

### 6.2 User barge-in

User barge-in is a media reflex, not an active-interruption policy decision:

1. receive normalized `speech_started`;
2. stop local playback immediately;
3. cancel the active provider response;
4. clear or truncate unplayed output according to adapter capabilities;
5. persist delivered duration and unfinished response metadata;
6. enter `USER_BARGE_IN`, then `RECOVERING`;
7. listen to the user's new intent before deciding whether to resume.

### 6.3 Active AI interruption levels

| Level | Allowed reasons |
|---|---|
| `off` | None; user barge-in still works |
| `low` | safety-critical or clearly destructive factual premise |
| `normal` | low plus sustained off-topic or repeated evasion |
| `strict` | normal plus time budget and repetition controls |

The gate must require all applicable conditions:

- minimum speech window has elapsed;
- transcript evidence is stable across multiple updates or a clause is finalized;
- proposal confidence meets the reason-specific threshold;
- the user is not self-correcting;
- ASR confidence is not low;
- per-question and per-session interruption caps are not exceeded;
- cooldown since the previous interruption has elapsed;
- accessibility or user preference does not forbid the action.

Recommended starting defaults:

```text
minimum active-interruption window: 10 seconds
off-topic persistence: 8 seconds
cooldown: 30 seconds
maximum active interruptions per question: 1
maximum active interruptions per session: 4
normal confidence threshold: 0.85
critical-fact threshold: 0.92 plus grounded evidence
```

These are experiment defaults, not permanent truths. They must be configurable and
calibrated with labeled sessions.

### 6.4 Redirect utterance constraints

- one sentence;
- no praise filler;
- identify the reason without sounding punitive;
- restate only one target question;
- do not reveal an answer in examination mode;
- no interruption may contain a new independent question stack.

## 7. Recovery protocol

Persist an `InterruptionContext` for every interrupted assistant response:

```json
{
  "response_id": "provider-response-id",
  "item_id": "provider-item-id",
  "original_question_id": "question-id",
  "generated_text": "...",
  "delivered_text": "...",
  "played_audio_ms": 1430,
  "unfinished_intent": "explain why evidence is insufficient",
  "user_new_intent": null,
  "reason": "USER_BARGE_IN",
  "resume_policy": "pending"
}
```

Allowed recovery actions:

```text
ABANDON_RESPONSE
ANSWER_USER_THEN_RETURN
RESUME_ORIGINAL_QUESTION
RESTATE_ORIGINAL_QUESTION
MOVE_ON
END_SESSION
```

Recovery is selected only after enough of the user's new turn is known. The system
must not automatically continue the cancelled sentence over the user.

## 8. Persistence changes

Prefer append-only events, consistent with ADR-002.

Proposed additions:

### ConversationTransition

```text
id
voice_session_id
from_state
to_state
trigger_signal_id
reason_code
policy_version
created_at
```

### InterruptionEvent

```text
id
voice_session_id
question_id
direction: user_to_ai | ai_to_user
reason_code
confidence
evidence_text
response_id
played_audio_ms
recovery_action
recovery_succeeded
created_at
```

`VoiceEvent` remains the raw/normalized event log. Existing JSON metrics remain a
compatibility snapshot, while reports aggregate from append-only events.

## 9. Provider-specific implementation notes

### OpenAI

- keep WebRTC for browser media;
- use semantic VAD as the default automatic mode;
- preserve push-to-talk fallback;
- WebRTC handles unplayed-audio truncation on user interruption, but the application
  still records response, item and timing evidence;
- application-gated experiments may set response creation or interruption flags
  differently, but must be feature-flagged.

### Qwen

- add normalized support for `server_vad`, `smart_turn` and manual mode where the
  selected model supports them;
- stop browser playback immediately before waiting for server cancellation;
- record `response.done` cancellation reason (`turn_detected` or
  `client_cancelled`);
- benchmark the existing `qwen3-omni-flash-realtime` against a supported Qwen3.5
  realtime model behind a feature flag;
- never silently replace a configured model.

## 10. API outline

```text
GET   /api/voice/capabilities
PATCH /api/voice/sessions/{id}/policy
GET   /api/voice/sessions/{id}/state
POST  /api/voice/sessions/{id}/signals
GET   /api/voice/sessions/{id}/timeline
GET   /api/voice/sessions/{id}/interruption-report
```

Policy update request:

```json
{
  "turn_mode": "semantic",
  "active_interruption_level": "normal",
  "thinking_pause_tolerance": "long",
  "max_active_interruptions": 4
}
```

## 11. Delivery slices

### M1: Observability before behavior change

- normalized provider events;
- canonical state machine in shadow mode;
- transition timeline and latency metrics;
- no active AI interruption.

### M2: Reliable user barge-in and recovery

- adapter cancellation contract;
- unfinished response context;
- deterministic recovery actions;
- reconnect handling.

### M3: Active interruption in observe-only mode

- detector proposals are logged but never executed;
- build labeled false-positive and missed-interruption datasets;
- calibrate thresholds by mode.

### M4: Controlled rollout

- enable `low`, then `normal`, behind feature flags;
- keep `strict` experimental;
- add UI controls and per-session explanations.

### M5: Release hardening

- provider parity suite;
- load, reconnect and long-session tests;
- migration, rollback and Docker Compose rehearsal;
- final behavioral evaluation report.

## 12. Non-goals

v0.6 does not include:

- facial emotion, personality or honesty inference;
- voice-based scoring;
- digital avatars;
- hardware integration;
- replacing the v0.5 cognitive engine;
- a trained proprietary policy model;
- mandatory active interruption.

## 13. Definition of done

v0.6 is complete only when:

- both providers emit the same canonical lifecycle for equivalent scenarios;
- user barge-in stop success exceeds 95% in the test matrix;
- active interruption remains within the false-positive gate in labeled sessions;
- every interruption has a reason, evidence and recovery record;
- reconnect and duplicate events cannot corrupt state;
- reports and cognitive state use finalized transcript evidence;
- text examination and v0.5 adaptive behavior pass regression tests;
- Docker Compose upgrade preserves `.env`, `data/`, uploads and the database.

## 14. Primary provider references

- [OpenAI Realtime VAD](https://developers.openai.com/api/docs/guides/realtime-vad)
- [OpenAI Realtime conversation and interruption handling](https://developers.openai.com/api/docs/guides/realtime-conversations)
- [Qwen-Audio realtime interaction modes](https://help.aliyun.com/en/model-studio/qwen-audio-realtime-user-guides)
- [Qwen-Audio realtime server events](https://help.aliyun.com/en/model-studio/qwen-audio-realtime-server-events)
- [Qwen-Omni realtime models and WebRTC](https://help.aliyun.com/zh/model-studio/realtime)

Provider capabilities and model names are time-sensitive. Re-verify these primary
sources before implementation or changing defaults.
