# v0.9 Model Governance, Quota and Rate Limiting

Status: WP-09 implemented on `research/v0.9.0`

## 1. Scope

WP-09 makes organization policy authoritative before any runtime model provider is
constructed or contacted. It covers text, structured JSON, multimodal analysis,
Golden Dataset generation, benchmark execution, joint analysis and realtime voice
connection admission.

The implementation separates:

- durable policy and quota state in PostgreSQL/SQLite;
- authoritative reservation and actual-usage evidence in the database;
- fast rolling request, token and concurrency admission in Redis;
- provider execution behind `GovernedModelProvider`;
- redacted administrative API and audit evidence.

Offline template probe CLIs remain evaluation utilities and do not represent a
tenant runtime call. Production API and worker paths must use
`governed_provider(...)` or the explicit realtime admission helpers.

## 2. Runtime sequence

```text
requested profile
  -> organization policy lookup
  -> task/profile/data-classification decision
  -> quota row lock and durable reservation
  -> atomic Redis request/token/concurrency admission
  -> provider construction
  -> provider call
  -> settle actual provider/model/tokens/cost/latency
  -> release concurrency lease
```

An authoritative denial stops before provider construction. A provider failure
marks its reservation failed. Ordered fallback is attempted only when the requested
profile was itself allowed and the fallback candidate also passes the current
policy. Because an upstream failure may still be billable, failed calls retain their
reservation as accounted estimated cost instead of reopening quota for free retries.

Realtime voice performs the same decision during session creation and again before
the OpenAI SDP or Qwen WebSocket upstream connection. The connection handshake is
recorded as a governed call. Media token reconciliation is provider dependent; the
current ledger records the authoritative connection, selected model and handshake
latency without inventing unavailable audio token counts.

## 3. Policy model

`OrganizationModelPolicy` is unique per organization and versioned. Its digest is
copied into each usage row.

Task rules use stable public task families. `planner`, `analyzer`, and `reporter`
also authorize the internal agent names `session_planner`, `answer_analyzer`, and
`report_generator`. Exact internal names remain accepted for narrow policies, and
`*` authorizes every task for the matching provider/model rule.

Policy controls:

- provider and model-pattern allowlist;
- allowed Agent/task names;
- ordered fallback profiles or deny-only behavior;
- maximum data classification for external providers;
- provider-retention declaration;
- hard or soft quota behavior;
- monthly, per-session and per-request budgets;
- soft-limit warning ratio;
- organization and principal requests per minute;
- organization token units per minute;
- maximum concurrent calls.

Project classification is one of:

```text
public < internal < confidential < restricted
```

External providers are OpenAI, Anthropic, Gemini and Qwen. By default they may
receive up to `confidential`; `restricted` requires a local profile such as Ollama
unless an administrator explicitly changes the organization policy.

## 4. Usage ledger

`ModelUsageLedger` records:

- organization, project, exam session and actor;
- request ID and task type;
- data classification;
- requested profile and fallback origin;
- actual provider and model;
- reservation and settled estimated cost;
- input/output tokens, latency and retry count;
- policy ID, version and digest;
- status, denial reason, rate-limit scope and soft-limit flag.

Statuses are:

```text
reserved -> completed
reserved -> failed
reserved -> denied
request  -> denied
```

The ORM rejects deletion. PostgreSQL grants the runtime role `SELECT`, `INSERT` and
`UPDATE`, but not `DELETE`, and applies forced organization RLS. Downgrade refuses
to drop non-empty usage evidence.

## 5. Quota correctness

PostgreSQL serializes quota reservations by locking the organization policy row.
Committed cost and active reservations are summed inside that transaction, so API
and worker reservations cannot independently pass the same hard boundary.

Hard mode:

- persists the denial;
- writes a redacted audit event;
- returns stable HTTP 429 error codes;
- never constructs the provider.

Soft mode:

- permits the call;
- marks `soft_limit_exceeded`;
- preserves the applicable quota reason for dashboards and alerting.

The monthly period uses UTC calendar boundaries. Zero budget values disable the
corresponding budget dimension.

## 6. Redis admission

One Lua script atomically checks and increments:

- organization requests per minute;
- principal requests per minute;
- organization token units per minute;
- organization concurrent calls.

Concurrency uses expiring sorted-set leases. Normal completion and provider failure
release the lease. Stale leases expire after
`MODEL_CONCURRENCY_LEASE_SECONDS`.

Production defaults to fail closed when Redis is unavailable. A deliberate
fail-open deployment may set `MODEL_RATE_LIMIT_REQUIRED=false`; it then uses the
process-local limiter without falsely recording a denial.

## 7. Administrative API

```text
GET /api/v1/organizations/{organization_id}/model-policy
PUT /api/v1/organizations/{organization_id}/model-policy
GET /api/v1/organizations/{organization_id}/quota
PUT /api/v1/organizations/{organization_id}/quota
GET /api/v1/organizations/{organization_id}/usage
GET /api/v1/organizations/{organization_id}/usage/export
```

Policy and quota updates require `policy.manage` and are audited in the same
transaction. Reads require `policy.read`; usage and export require `usage.read`.
Usage summaries group completed calls by profile, project and task/Agent. The
bounded NDJSON export contains policy and accounting metadata, never prompts,
answers, document text or credentials.

## 8. Configuration

```env
MODEL_GOVERNANCE_ENABLED=true
MODEL_RATE_LIMIT_BACKEND=redis
MODEL_RATE_LIMIT_REQUIRED=true
MODEL_RATE_LIMIT_WINDOW_SECONDS=60
MODEL_CONCURRENCY_LEASE_SECONDS=300
MODEL_RESERVED_OUTPUT_TOKENS=4096
```

`MODEL_RATE_LIMIT_BACKEND=memory` is suitable only for tests and single-process
local evaluation. Multi-worker production must use Redis and PostgreSQL.

## 9. Error contract

Stable governance codes include:

```text
model_policy_denied
model_policy_changed
monthly_quota_exceeded
session_quota_exceeded
per_request_quota_exceeded
organization_rate_limited
principal_rate_limited
organization_token_rate_limited
organization_concurrency_limited
rate_limiter_unavailable
```

Rate responses use HTTP 429 and include `Retry-After` where known. Admission backend
failure uses HTTP 503 when fail-closed.

## 10. Verification

Deterministic tests cover:

- policy digest/version behavior;
- no provider construction after policy or hard-quota denial;
- restricted-data external-provider denial;
- actual provider/model and policy snapshot evidence;
- hard and soft quota behavior;
- atomic concurrent-call admission and lease release;
- fail-open ledger consistency;
- realtime policy and connection accounting;
- policy/quota/usage API authorization and redacted export;
- immutable ledger behavior and downgrade refusal.

The PostgreSQL CI proof also verifies forced RLS and confirms the runtime role has no
`DELETE` privilege on policy or usage evidence.
