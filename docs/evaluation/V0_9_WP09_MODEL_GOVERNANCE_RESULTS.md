# v0.9 WP-09 Model Governance Acceptance Results

Date: 2026-07-28
Branch: `research/v0.9.0`
Package version: `0.8.0.dev0`
Release status: research increment, no v0.9 tag

## Scope

This acceptance run covers organization model policy, project data classification,
hard/soft quota, Redis-compatible admission behavior, durable usage evidence,
controlled fallback, realtime upstream admission and administrative usage APIs.

## Deterministic gates

```text
WP-09 + realtime focused tests     23 passed
Complete SQLite regression suite  268 passed
Ruff                              passed
Python compileall                  passed
JavaScript syntax                 passed
Alembic heads                     20260728_0015 (head)
git diff --check                  passed
```

The Windows runner printed an `asyncio` proactor access-violation message during
interpreter teardown after Pytest had completed. Pytest returned exit code 0 and all
268 collected tests passed. Linux GitHub CI remains the authoritative clean-process
gate.

## Acceptance mapping

### Disallowed provider is never called

Passed. Tests replace the provider builder with a fail-on-use spy. Policy,
classification and hard-quota denials occur before provider construction and leave
a denied ledger/audit record.

Realtime voice is checked during session creation and again before OpenAI SDP or
Qwen WebSocket upstream connection. A denied voice model does not create a voice
session or contact the upstream provider.

### Concurrent hard limits

Passed locally for:

- process-atomic hard budget reservation;
- organization concurrent-call admission;
- lease release and subsequent admission;
- request, token and principal/organization limiter semantics.

PostgreSQL uses `SELECT ... FOR UPDATE` on the organization policy row. The GitHub
PostgreSQL job is required to confirm the database-backed cross-worker path.

### Actual model and policy snapshot

Passed. Completed usage evidence records:

- requested profile;
- actual provider and model;
- fallback origin;
- organization/project/session/actor ownership;
- policy ID, version and digest;
- classification, tokens, latency, retry and cost fields.

The initial and updated policy versions use the same canonical SHA-256 digest
algorithm.

### Fallback and failed cost

Passed. Ordered fallback occurs only after both the requested and fallback profiles
pass current policy. Provider failure creates a failed ledger. Its reservation
remains accounted estimated cost because an upstream failure may still be billable.

### Data classification

Passed. Projects persist `public`, `internal`, `confidential` or `restricted`.
External providers are rejected when classification exceeds the organization
policy boundary.

### API, authorization and redaction

Passed. Policy/quota updates require `policy.manage`; reads require `policy.read`;
usage and export require `usage.read`. Updates produce administrative audit
evidence. Usage is grouped by profile, project and task/Agent. NDJSON export
contains accounting metadata and excludes prompt, answer and document content.

### Migration and immutability

Passed locally. Migration `20260728_0015` adds classification, policy and usage
tables. ORM deletion is rejected and downgrade refuses to destroy non-empty usage
evidence.

The PostgreSQL RLS verifier now requires both tables to have forced tenant policy
and confirms `ai_examiner_runtime` has no `DELETE` privilege.

## Operational behavior

Production requires:

```env
MODEL_GOVERNANCE_ENABLED=true
MODEL_RATE_LIMIT_BACKEND=redis
MODEL_RATE_LIMIT_REQUIRED=true
```

`/ready` now reports the model-governance backend. A required Redis outage makes
readiness fail and model admission returns HTTP 503. Deliberate fail-open mode uses
the process-local limiter without writing a false denial.

## Residual limitations

- Realtime voice handshake usage is authoritative, but media-token reconciliation
  depends on provider-side trusted usage events. The server does not invent audio
  token counts it cannot independently verify.
- The in-memory limiter is for tests and single-process local evaluation only.
- Offline template provider-probe CLIs are evaluation utilities outside tenant
  runtime governance.
- Docker was not available in the local Windows environment. GitHub Linux and
  PostgreSQL CI must pass before this increment is accepted on the remote branch.

## Verdict

Local WP-09 acceptance: **passed**.

Remote branch acceptance remains pending the GitHub SQLite and PostgreSQL jobs.
