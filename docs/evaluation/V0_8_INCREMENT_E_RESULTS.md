# v0.8 Increment E Conversation Policy Results

## Scope

This increment completes WP-07 by applying one effective conversation and
assistance contract to text, OpenAI Realtime and Qwen Realtime sessions.

It remains a development increment on `develop/v0.8.0`.

## Action authorization

The deterministic Policy Controller first selects a requested action, then checks
the template allowlist. A forbidden action cannot be executed. The controller
chooses an allowed, deterministic fallback or rejects a malformed policy with no
safe executable action.

Every returned decision records:

```text
requested action
effective action
allowed actions
fallback reason
hint permission
correction permission
answer-disclosure permission
active-interruption state
```

All template conversation policies must contain `END`.
`template-validator-v2` enforces this terminal invariant.

## Assistance and disclosure

Follow-up limits and hint availability come from the immutable template snapshot.
Realtime instructions explicitly prohibit expected-point or ideal-answer disclosure
when the effective policy disallows it. Corrections retain their configured timing
boundary.

## Interruption semantics

Two behaviors are intentionally separate:

- learner barge-in stops examiner audio and remains available;
- proactive examiner interruption requires both template permission and user
  opt-in.

A client request cannot enable proactive interruption when the template disabled
it. A user can always turn optional proactive interruption off.

## Provider parity

OpenAI and Qwen voice sessions created from equivalent template inputs store the
same effective conversation policy. Both receive identical trusted policy
instructions; provider transport and voice/model settings remain separate.

## Version audit

```text
template validator       template-validator-v2
conversation policy      conversation-policy-v1
adaptive selector        adaptive-v2
template adaptive path   adaptive-template-v2
template fixed path      fixed-template-v1
```

Existing built-in versions are not mutated. Startup idempotently appends a v2
validation run when a persisted built-in version has only an older validation
record.

## Verification

```text
new conversation-policy tests      5 passed
targeted template tests            47 passed
full pytest                        99 passed
full Ruff                          passed
JavaScript syntax                  passed
git diff --check                   passed
```

Tests cover forbidden hint fallback, terminal-action validation, interruption
consent, text decision audit and OpenAI/Qwen policy parity.

The Windows interpreter continues to print the pre-existing AnyIO `TestClient`
shutdown access-violation diagnostic after all assertions complete. Pytest exits
with code zero.

## Held work

This increment does not yet apply template assessment dimensions, aggregate
policies, report sections or required disclaimers. Those remain WP-08.
