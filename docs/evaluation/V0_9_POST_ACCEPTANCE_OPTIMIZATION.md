# v0.9 Post-Acceptance Optimization

Date: 2026-07-30

Branch: `research/v0.9.0`

Status: implementation and local regression passed; deployed Qwen verification is
recorded after staging promotion.

## Trigger

The deployed v0.9 acceptance passed 45 of 45 workflows, but its real Qwen Plus
Planner request took `153,742 ms`. The output was valid; the synchronous browser
request was not an acceptable interactive experience.

## Changes

### Recoverable blueprint jobs

Interactive blueprint generation now uses:

```text
POST blueprint/async
-> persisted idempotent job
-> Celery worker or single-process background dispatcher
-> Planner
-> cancellation checkpoint
-> evidence linking and blueprint persistence
-> job result
```

The old synchronous endpoint remains available for compatibility.

The job contract includes:

- organization-scoped idempotency;
- current-capability revalidation before protected resource access;
- lease ownership and heartbeat recovery;
- progress and elapsed-time UI;
- explicit `failed`, `cancelled` and `dead_letter` states;
- cooperative cancellation before result persistence;
- a complete blueprint in `job.result.blueprint`.

### Direct-process staging

`CELERY_ALWAYS_EAGER=true` no longer forces the HTTP request to wait for the model.
FastAPI sends the persisted job response first and runs eager dispatch as a
background task. Docker Compose deployments continue to use Redis and Celery.

Eager task failures retain the worker's terminal status and error code. They are no
longer overwritten with the misleading `queue_unavailable` error.

### Qwen latency control

`QWEN_ENABLE_THINKING=false` is the interactive default. Operators can enable
thinking for quality-sensitive batch evaluation:

```env
QWEN_ENABLE_THINKING=true
```

This is a model-quality tradeoff, not a universal speed preset. Blueprint quality
must still pass the frozen template and grounding evaluations before promotion.

## Local verification

```text
Ruff                              passed
JavaScript syntax                 passed
Full pytest                       passed (303 tests)
Async blueprint focused tests     passed
Legacy synchronous contract       passed
Idempotent duplicate submission   passed
Pre-claim cancellation            passed
```

A real Uvicorn HTTP smoke test with the Mock provider measured:

```text
enqueue response        26.2 ms
HTTP status             202
initial job status      queued
terminal job status     completed
blueprint persisted     yes
```

The known Windows AnyIO shutdown access-violation diagnostic appeared after pytest
reported 100 percent and returned exit code zero. Linux CI remains authoritative.

## Promotion gate

Before this optimization is accepted on staging:

1. deploy the exact commit;
2. verify `/health` and `/ready`;
3. submit one real `qwen:qwen-plus` blueprint through the asynchronous endpoint;
4. record enqueue latency, terminal latency, provider/model and question count;
5. verify the browser remains responsive and displays progress;
6. confirm one repeated idempotency key does not create a second blueprint;
7. rerun the deployed acceptance suite;
8. run GitHub Linux CI.

No API key, prompt, document body or model response is stored in this report.
