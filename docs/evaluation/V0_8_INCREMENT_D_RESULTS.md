# v0.8 Increment D Planner and Selector Results

## Scope

This increment completes WP-06 by making the compiled session-template contract
control blueprint planning and adaptive question eligibility.

It remains a development increment on `develop/v0.8.0`.

## Planner contract

Blueprint generation resolves the template using the same precedence as session
creation and supplies this provider-neutral contract to the Planner:

```text
objectives
allowed question types
objective coverage minima
difficulty minimum/maximum
question limit
```

Provider output must stay within the allowed taxonomy and difficulty interval.
Question count is deterministically bounded, and every accepted question is mapped
to at least one declared objective.

The resulting blueprint stores template version, compiler fingerprint, resolution
source and a coverage audit. If the configured question limit makes complete
coverage impossible, the blueprint reports the exact unmet objectives with
`status=impossible`; it does not claim successful coverage.

## Adaptive selector contract

The selector reads `question_selection` from the session's immutable snapshot. It:

- filters undeclared question types;
- filters difficulty outside the template bounds;
- clamps the target difficulty to the template interval;
- counts objective coverage from questions already asked;
- prioritizes eligible questions that satisfy an unmet required objective;
- retains the v0.5 knowledge-gap, uncertainty, importance, misconception,
  difficulty-fit and novelty scoring inside the eligible set.

Each adaptive decision stores the template fingerprint, allowed types, coverage and
difficulty policy used for that decision.

## Immutable template evolution

WP-06 needs `assumption` and `critical_reflection` question types. Published v1.1
was not edited. A new reviewed `academic.thesis_defense@1.2.0` version was added,
and startup now idempotently preserves all three versions.

## Verification

```text
new Planner/selector behavior tests    4 passed
targeted v0.5-v0.8 behavior tests     42 passed
full pytest                           94 passed
full Ruff                             passed
JavaScript syntax                     passed
git diff --check                      passed
```

Fixtures verify successful coverage, explicit impossible coverage, required
objective priority, type/difficulty filtering and decision audit metadata.

The Windows interpreter continues to print the pre-existing AnyIO `TestClient`
shutdown access-violation diagnostic after all assertions complete. Pytest exits
with code zero.

## Held work

This increment does not yet enforce template action allowlists, hint/disclosure
rules, rubric dimensions, report sections or required disclaimers. Those remain
WP-07 and WP-08.
