# v0.9 Post-Acceptance Optimization

Date: 2026-07-30

Branch: `research/v0.9.0`

Status: implemented, deployed and accepted on direct-process staging.

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

## Deployed verification

The exact optimization commit was deployed to the SeetaCloud direct-process
staging service:

```text
source commit             e2713368dd409deb4a460dee07906d8e6db763f3
service port              6008
runtime worktree          ai-examiner-v0.9-staging
GET /health               200
GET /ready                ready
provider/model            qwen / qwen-plus
QWEN_ENABLE_THINKING      false
```

The asynchronous blueprint request produced:

```text
enqueue HTTP status       202
enqueue latency           41.7 ms
initial job status        queued
terminal job status       completed
terminal latency          80,331.4 ms
worker attempts           1
questions                 6
browser health during job 200
duplicate enqueue latency 36.8 ms
duplicate reused job      yes
```

Compared with the original synchronous `153,742 ms` staging measurement, the
provider stage was about 47.8 percent faster in this run. More importantly, the
interactive HTTP request returned in under 50 ms and no longer held the browser
request open while Qwen planned the blueprint.

The old synchronous endpoint was retained and rechecked during the isolated
acceptance run. It completed successfully in `44,058 ms`.

## Deployed acceptance

The complete destructive acceptance protocol was rerun on an isolated service and
fresh SQLite database:

```text
tests                      45
passed                     45
failed                     0
real Qwen planner          44,058 ms
template health            252 ms
deletion retry             145 ms
```

The first rehearsal seeded the independent approval actor with the ordinary
`reviewer` role, which correctly lacked `retention.manage`. The clean rerun used
an administrator as the independent approver, matching the documented acceptance
protocol, and passed all 45 workflows. This was test-fixture correction rather
than a product permission change.

GitHub Linux CI run `30505778777` completed successfully for the optimization
commit.

The sanitized machine-readable result is stored in
`docs/evaluation/evidence/v0_9/post-acceptance-optimization.json`.

## Release decision

The latency and recoverability defect is closed for direct-process staging.
Enterprise release promotion remains held because this host still cannot validate
the PostgreSQL, Redis worker, MinIO/S3, OIDC, TLS and disaster-recovery gates. No
v0.9 release-candidate tag is authorized by this result.
