# ADR-003: Application-owned realtime conversation control

Status: Proposed for v0.6  
Date: 2026-07-20

## Context

v0.5 delegates turn detection, response creation and user barge-in largely to each
realtime model. This keeps latency low, but provider events and interruption
semantics differ. A model prompt also cannot reliably decide when an examiner
should wait, redirect, challenge, interrupt or recover.

The v0.5 cognitive engine is the authority for answer analysis, mastery state and
question selection. Realtime models must not bypass that authority merely because
they can produce natural speech.

## Decision

v0.6 will use an application-owned, two-speed control architecture:

1. A media reflex layer performs user barge-in immediately using provider-native
   cancellation and output-buffer controls. It does not call an LLM.
2. A deterministic conversation timing state machine normalizes provider events,
   owns legal state transitions and records every interruption.
3. An active-interruption detector may propose a finite action from partial or
   finalized transcripts. A deterministic gate decides whether the proposal is
   allowed.
4. The existing v0.5 analyzer, evaluator, knowledge state and adaptive selector
   remain authoritative and consume finalized answer evidence only.

Provider-specific behavior will be isolated behind a `RealtimeProviderAdapter`.
The policy layer will consume normalized `VoiceSignal` events and capability flags,
not raw OpenAI or DashScope event names.

## Safety constraints

- Active AI interruption is disabled by default during the first rollout.
- User barge-in remains available in every automatic mode.
- Active interruption can be set to `off`, `low`, `normal` or `strict` per session.
- Every interruption has a reason code, confidence, timing evidence and recovery
  result.
- A partial transcript alone cannot directly trigger an active interruption.
- Accent, voice, emotion, hesitation or inferred personality cannot affect scoring.
- Text examination must continue to work if all realtime providers are unavailable.

## Consequences

### Positive

- consistent policy across OpenAI and Qwen;
- replayable and testable timing decisions;
- provider upgrades do not rewrite cognitive policy;
- false interruptions and recovery quality become measurable;
- unfinished speech and assistant responses can be handled explicitly.

### Costs

- more client and server state coordination;
- provider capability differences must be tested continuously;
- active interruption needs labeled conversation data, not only unit tests;
- WebSocket playback reconciliation is more complex than WebRTC-managed playback.

## Rejected alternatives

### Put all timing rules in the realtime model prompt

Rejected because prompts do not enforce legal transitions, cooldowns, evidence
logging or provider parity.

### Route every audio frame through the policy server

Rejected because it adds latency and makes the application media path a bottleneck.

### Let the realtime model update mastery directly

Rejected because it breaks the v0.5 evidence and replay guarantees.
