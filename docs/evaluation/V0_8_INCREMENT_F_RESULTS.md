# v0.8 Increment F Assessment and Report Results

Date: 2026-07-23

Branch: `develop/v0.8.0`

Package version: `0.8.0.dev0`

## Scope

Increment F implements WP-08. It applies the immutable session template snapshot
to answer assessment and report generation for both text answers and finalized
realtime voice transcripts.

## Runtime contracts

- Evaluator: `template-assessment-v1`
- Reporter: `assessment-report-v3`
- Validator: `template-validator-v3`
- Assisted blend, when selected: 70% independent plus 30% final assisted result

Registered assessment dimensions:

```text
correctness
completeness
evidence_reasoning
boundary_awareness
```

Every registered dimension maps only to reviewed answer-analysis components.
Voice timing, pauses, interruptions, latency, preferences, inferred emotion and
presentation style are intentionally outside this mapping.

## Deterministic score path

```text
answer analysis components
-> registered dimension mapping
-> template scale
-> template dimension weights
-> question assessment
-> independent/assisted policy
-> objective evidence groups
-> objective weights
-> total or no-total report policy
```

Question and report scores can be recomputed from stored normalized dimension
scores and weights. Each dimension score includes answer and rubric evidence.
Objective scores retain the supporting turn, answer quote, source excerpt and
dimension assessments.

## Behavioral coverage

The Increment F tests verify:

- exact dimension-weight recomputation;
- complete answer and rubric evidence;
- immutable template objective and dimension weights;
- section order and required disclaimer selection;
- objective-weighted total calculation;
- valid reports with no exposed total score;
- text and finalized voice use the same evaluator path;
- voice and interaction signals do not affect correctness;
- unregistered assessment dimensions fail semantic validation;
- legacy report aggregation remains compatible.

## Verification

```text
Targeted assessment/report tests   41 passed
Full pytest                        104 passed
Ruff                               passed
JavaScript syntax                  passed
Alembic head                       20260723_0007
Alembic metadata drift             none
Tracked-source secret scan         no key patterns found
```

On this Windows host, pytest still prints the previously documented AnyIO
shutdown access-violation diagnostic after all assertions pass. The test process
returns exit code zero.

## Held gates

This increment does not create a v0.8 release or tag. WP-09 through WP-12 remain
open, including the remaining reviewed built-in scenarios, structured editor,
governance/evaluation gates and release hardening.
