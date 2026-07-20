# v0.6 Implementation Backlog

## 1. Execution rules

- Base implementation on the accepted v0.5 release commit, not on `main` while
  `main` remains v0.4.1.
- Keep `research/v0.6.0` documentation-only.
- Create `develop/v0.6.0` only after ADR-003 review.
- Use one feature branch and one reviewable commit series per work package.
- Do not change user-visible timing behavior in the shadow-FSM work package.
- Do not enable active AI interruption before the observe-only gate passes.
- Preserve text examination and the v0.5 adaptive cognitive engine.

## 2. Work packages

### WP-01: Normalized event schema

Branch: `feature/v0.6-voice-signals`

Deliverables:

- `VoiceSignalType`, `VoiceSignal` and provider capability schemas;
- stable reason-code enums;
- conversion fixtures for current OpenAI and Qwen events;
- unknown-event passthrough logging.

Acceptance:

- recorded events normalize deterministically;
- duplicate provider event IDs are idempotent;
- no policy module imports provider-specific event constants.

### WP-02: Provider adapter boundary

Branch: `feature/v0.6-provider-adapters`

Deliverables:

- `RealtimeProviderAdapter` protocol;
- OpenAI and Qwen implementations;
- cancel, clear, truncate and turn-detection capability matrix;
- mock replay adapter.

Acceptance:

- shared contract tests pass for both providers;
- unsupported actions return explicit capability errors;
- configured models are never silently replaced.

### WP-03: Shadow conversation FSM

Branch: `feature/v0.6-shadow-fsm`

Deliverables:

- pure transition reducer;
- legal-transition table;
- append-only transition persistence;
- browser/server state-divergence telemetry;
- timeline debug endpoint.

Acceptance:

- no user-visible behavior changes;
- deterministic replay reaches the expected final state;
- illegal and duplicate transitions cannot corrupt state.

### WP-04: Migration and compatibility

Branch: `feature/v0.6-conversation-events`

Deliverables:

- `ConversationTransition` and `InterruptionEvent` tables;
- migration and rollback scripts;
- compatibility aggregation into existing `VoiceSession.metrics`;
- project deletion coverage.

Acceptance:

- v0.5 data opens without manual changes;
- migration and rollback are rehearsed on a copied database;
- no existing session, document or knowledge state is lost.

### WP-05: User barge-in reflex

Branch: `feature/v0.6-barge-in`

Deliverables:

- immediate browser playback stop;
- adapter cancel/clear/truncate path;
- played-audio duration measurement;
- provider cancellation-reason persistence;
- noisy false-start handling.

Acceptance:

- barge-in success >= 95% in the device matrix;
- p95 playback-stop target <= 300 ms;
- no cancelled, unplayed assistant content is treated as delivered evidence.

### WP-06: Interruption context and recovery

Branch: `feature/v0.6-recovery`

Deliverables:

- unfinished response context;
- recovery action reducer;
- user-question-then-return behavior;
- reconnect recovery;
- recovery timeline UI.

Acceptance:

- interrupted responses do not resume over the user;
- recovery action accuracy >= 90% on the recovery corpus;
- original question identity is preserved when returning.

### WP-07: Turn timing controls

Branch: `feature/v0.6-turn-timing`

Deliverables:

- semantic, acoustic and push-to-talk modes as capabilities permit;
- thinking-pause preferences;
- one-response-at-a-time gate;
- first-audio and end-of-turn latency metrics;
- provider/model feature flags.

Acceptance:

- self-correction and thinking-pause cases do not trigger stacked responses;
- text mode remains independent of realtime availability;
- unsupported mode selection is rejected before media starts.

### WP-08: Active-interruption detector in observe-only mode

Branch: `feature/v0.6-interruption-observer`

Deliverables:

- finite detector output schema;
- stable transcript window;
- reason-specific confidence;
- transcript evidence and proposed timing;
- observer dashboard/export.

Acceptance:

- detector cannot send cancel or speech commands;
- every proposal is replayable from stored evidence;
- at least 200 candidate segments are collected and labeled.

### WP-09: Deterministic policy gate

Branch: `feature/v0.6-interruption-gate`

Deliverables:

- level policy (`off`, `low`, `normal`, `strict`);
- cooldown and caps;
- ASR confidence and self-correction suppression;
- grounded critical-fact validation;
- feature flags and instant rollback.

Acceptance:

- active interruption in `off` mode is impossible;
- all executed interruptions have evidence and a reason;
- false-positive release gate passes before `normal` is enabled.

### WP-10: Voice controls and accessibility UI

Branch: `feature/v0.6-voice-controls`

Deliverables:

- icon-based pause, stop and push-to-talk controls;
- interruption-level selector;
- thinking-pause preference;
- connection/recovery status;
- accessible labels, keyboard control and mobile layout.

Acceptance:

- controls do not resize during state changes;
- microphone permissions and errors are actionable;
- active interruption can be disabled before and during a session.

### WP-11: Behavioral evaluation runner

Branch: `feature/v0.6-voice-evals`

Deliverables:

- recorded-event replay tests;
- latency aggregation;
- interruption confusion matrix;
- provider parity report;
- recovery evaluation;
- regression-case import.

Acceptance:

- evaluation runs without paid APIs for recorded fixtures;
- report records provider, model, prompt, policy and dataset versions;
- release gates fail CI when thresholds regress.

### WP-12: Release hardening

Branch: `release/v0.6.0`

Deliverables:

- clean Docker Compose build and upgrade rehearsal;
- data backup/restore verification;
- reconnect and 30-minute session soak tests;
- updated API, architecture, migration and deployment docs;
- secret scan and release report.

Acceptance:

- all v0.5 regressions pass;
- all applicable v0.6 gates pass;
- package/docs agree on `0.6.0rcN`;
- RC tag is annotated and immutable.

## 3. Dependency order

```text
WP-01 -> WP-02 -> WP-03 -> WP-04
                   |
                   +-> WP-05 -> WP-06 -> WP-07
                                  |
                                  +-> WP-08 -> WP-09
                                             |
                                             +-> WP-10

WP-01..WP-10 -> WP-11 -> WP-12
```

## 4. First implementation task

Start with WP-01 only. Its pull request must contain schemas, fixtures and tests,
but no UI change and no modification to active provider behavior. This establishes
the contract every later package depends on.
