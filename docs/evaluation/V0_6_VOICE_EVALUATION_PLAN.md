# v0.6 Realtime Conversation Evaluation Plan

## 1. Purpose

This plan evaluates behavior, timing and recovery. A successful API call or a
natural-sounding voice is not sufficient evidence that the examiner works well.

## 2. Evaluation layers

### 2.1 Deterministic state tests

For each provider event trace, assert:

- legal state transitions;
- idempotency under duplicate events;
- no simultaneous assistant responses;
- no assistant output while `USER_SPEAKING`;
- terminal behavior after `COMPLETED`;
- recovery after reconnect;
- preserved cognitive-state authority.

Use recorded JSON traces so tests do not require paid provider calls.

### 2.2 Media reflex tests

Measure from user speech onset to audible assistant stop:

```text
speech onset
-> provider/client detection
-> response cancel
-> playback stop
-> history reconciliation
```

Test desktop Chrome, Android Chrome and iOS Safari over:

- stable broadband;
- 4G/5G-like latency;
- packet loss and jitter;
- quiet and noisy rooms;
- headphones and speakers.

### 2.3 Turn-taking behavior tests

Include:

- short complete answer;
- long answer with natural pauses;
- filler such as "um" or "let me think";
- self-correction;
- sentence trailing off;
- background speech;
- user speaking while AI speaks;
- push-to-talk;
- repeated answer;
- sustained off-topic answer;
- direct user question;
- critical factual error;
- connection drop during each state.

### 2.4 Active-interruption evaluation

Every candidate segment is independently labeled by at least two judges:

```text
interrupt_now
wait
redirect_after_turn
give_hint_after_turn
correct_after_turn
```

Required labels also include reason, earliest acceptable interruption time and
latest useful interruption time.

The active-interruption detector is first evaluated in observe-only mode. It cannot
control production audio until its release gate passes.

## 3. Primary metrics

| Metric | Definition | v0.6 gate |
|---|---|---|
| User barge-in success | assistant playback stops after genuine user speech | >= 95% |
| Barge-in stop latency p95 | speech onset to playback stop | <= 300 ms target |
| First audio latency p50 | user turn completion to first assistant audio | <= 1.5 s target |
| First audio latency p95 | same, tail latency | <= 2.5 s target |
| False active interruption rate | executed interruption labeled `wait` | < 5%, stretch < 3% |
| Missed active interruption rate | `interrupt_now` with no timely action | < 15% after rollout |
| Recovery success | interruption followed by correct next policy action | >= 90% |
| State divergence | browser/server canonical states disagree > 1 s | < 1% of turns |
| Conversation control error | illegal transition, stacked response or lost turn | < 2% of sessions |
| Final transcript coverage | completed user turns persisted for cognition | >= 99% |
| Reason coverage | interruptions with valid reason and evidence | 100% |

Latency targets are release goals, not guarantees for every network or device.

## 4. Guardrail metrics

- interruption cap violations: zero;
- active interruptions while policy is `off`: zero;
- voice/accent/personality-based score features: zero;
- scoring from partial transcript: zero;
- active interruption without transcript evidence: zero;
- ungrounded critical-fact interruptions: zero in Golden cases;
- question stacking after redirect: below 5%;
- text-mode regression: zero critical failures.

## 5. Provider parity matrix

Run each scenario against:

```text
OpenAI automatic semantic turn mode
OpenAI push-to-talk
Qwen server VAD
Qwen smart/semantic turn mode when supported
Qwen push-to-talk
Mock recorded-event adapter
```

Compare normalized outcomes, not raw event names:

- final state;
- cancellation reason;
- whether unplayed content remains in context;
- persisted transcript;
- recovery action;
- latency distribution;
- cost and error rate.

## 6. Datasets

### 6.1 Recorded event traces

Sanitized raw provider events with expected normalized signals and transitions.

### 6.2 Turn boundary corpus

Audio and transcripts labeled for speech start, possible pause and true turn end.
Include Chinese, English and mixed-language academic answers.

### 6.3 Interruption policy corpus

At least 200 segments before enabling `normal` mode:

- 50 valid wait cases;
- 40 off-topic cases;
- 30 repetition/evasion cases;
- 30 self-correction cases;
- 20 critical-error cases;
- 20 user-question cases;
- 10 noise or false-start cases.

### 6.4 Recovery corpus

Interrupted assistant utterances paired with user intents and expected recovery
actions.

### 6.5 Regression corpus

Every production timing bug becomes a permanent replay trace.

## 7. Human review protocol

- remove model/provider names from samples;
- randomize sample order;
- evaluate timing and wording separately;
- collect acceptability on a 5-point scale;
- require adjudication when labels disagree;
- report agreement and confidence intervals, not only a mean score.

## 8. Rollout gates

### Gate A: Shadow state machine

Pass deterministic replay and state-divergence tests. No user-visible behavior
changes.

### Gate B: User barge-in

Pass stop-latency, truncation and recovery tests on both providers.

### Gate C: Observe-only active policy

Collect at least 200 labeled candidate segments and meet offline precision targets.

### Gate D: Low mode

Enable only safety and critical grounded errors for internal evaluation.

### Gate E: Normal mode

Enable sustained off-topic and repeated evasion only after false-positive and user
acceptability gates pass.

`strict` mode remains experimental unless separately accepted.

## 9. Release artifacts

The v0.6 release candidate must include:

- state transition coverage report;
- provider parity report;
- latency distribution by device/network;
- active-interruption confusion matrix;
- recovery action accuracy;
- labeled-data version and hash;
- model, prompt and policy versions;
- per-session cost comparison;
- known limitations and rollback instructions.
