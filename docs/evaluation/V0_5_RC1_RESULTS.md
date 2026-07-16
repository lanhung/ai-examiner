# v0.5.0 RC1 Evaluation Results

Date: 2026-07-16
Commit: to be filled by release tag
Policy: `adaptive-v1`

## Engineering gates

| Check | Result |
|---|---:|
| Automated tests | 27 passed |
| Total coverage | 87% |
| Adaptive selector coverage | 95% |
| Cognitive state service coverage | 93% |
| Policy benchmark coverage | 98% |
| Ruff | Passed |
| JavaScript syntax | Passed |
| v0.4.1 -> v0.5 migration | Passed |
| v0.5 -> base downgrade | Passed |
| base -> v0.5 re-upgrade | Passed |

## Covered behavior

- fixed order remains compatible;
- adaptive questions do not repeat in-session;
- same learner's next session uses prior concept evidence and novelty;
- active misconceptions receive selection priority;
- contradictory evidence lowers mastery while increasing confidence;
- duplicate finalization does not duplicate evidence events;
- event replay reproduces stored aggregate state;
- policy decisions include candidates, reasons, weights and versions;
- final adaptive voice transcripts create voice-sourced evidence events;
- reports and state APIs link concepts to answer evidence.

## Deterministic paired benchmark

`POST /api/blueprints/{id}/policy-benchmark` generates paired synthetic profiles from the same blueprint and compares fixed ordering with `adaptive-v1` under the same question limit. It reports important-gap discovery, waste rate and misconception response for:

- important high-value gap;
- persistent misconception;
- uneven mastery.

This benchmark is a regression instrument, not evidence of general real-world superiority.

Staging smoke result on the built-in mock blueprint with a two-question budget:

| Metric | Fixed | Adaptive | Delta |
|---|---:|---:|---:|
| Important gap discovery | 0.000 | 0.845 | +0.845 |
| Waste rate | 1.000 | 0.333 | -0.667 |
| Misconception response | 0.667 | 1.000 | +0.333 |

The smoke session produced two evidence events, two concept states, three decision records and two report knowledge-map entries.

## Pending final-release gates

- at least five frozen real-document datasets;
- paired repeated runs with real Analyzer models;
- human blind review of at least 20 decisions;
- Docker Compose staging build and restart persistence;
- real backup/restore rehearsal;
- real voice and paid-provider latency/cost measurements.

Until these gates pass, `adaptive` remains an evaluation choice and the API compatibility default remains `fixed`.
