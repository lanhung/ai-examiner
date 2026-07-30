# v0.9 Codex Full Audit

Date: 2026-07-30  
Branch: `research/v0.9.0`  
Tested source commit: `08408234d33010834a15225689101e0c8054dc52`  
Package version: `0.9.0.dev0`

## Decision

The v0.9 source tree is **deterministic-ready but not release-ready**.

The machine-readable release gate reported:

```text
passed     11
failed      0
blocked    12
status      deterministic_ready
```

No v0.9 release-candidate tag is authorized. The blocked checks require a real
enterprise environment with PostgreSQL, OIDC, Redis workers, S3/MinIO, TLS,
observability and recovery rehearsal.

## Verified engineering gates

```text
pytest collection                         312 tests across 48 files
pytest release-gate execution             passed
Ruff                                      passed
app.js syntax                             passed
enterprise.js syntax                      passed
tracked-source secret scan                passed
dependency audit                          0 known vulnerabilities
Alembic migration heads                   1 (20260728_0016)
protected route capability metadata       48 route-method pairs
frozen v0.8 Planner v6 regression         passed
Git working tree/source binding           passed
```

The Windows pytest process may print a third-party thread access-violation
diagnostic after the suite reaches 100%. Pytest still exits zero, and the
repository's Linux CI remains the authoritative process-cleanup result.

## Fresh runtime acceptance

A fresh isolated SQLite database was migrated through every Alembic revision and
started on local port `8021`. The test used the configured real
`qwen:qwen-plus` provider with thinking disabled.

```text
HTTP acceptance checks                    48
passed                                    48
failed                                     0
async blueprint enqueue                   25 ms
health during Qwen generation              3 ms
Qwen blueprint terminal completion   194,264 ms
idempotent duplicate submission           17 ms
```

The acceptance covers:

- health, readiness and enterprise static assets;
- unauthenticated denial and capability discovery;
- organization, membership and cross-tenant denial behavior;
- model policy, quota and usage records;
- tenant-owned document and evidence downloads;
- real Qwen asynchronous blueprint generation;
- retention, export, legal hold and verified deletion;
- dual-control denial and human review/appeal;
- durable job listing/recovery and append-only audit export;
- template health and voice configuration.

The asynchronous architecture behaved correctly: the service stayed responsive
during the 194-second provider call. The provider latency is nevertheless the
largest current user-experience risk and should be measured on Vultr before RC
promotion.

## API and repository surface

```text
OpenAPI paths                             117
OpenAPI operations                        140
runtime log ERROR/Traceback findings        0
tracked runtime data or secret files        0
Compose YAML files parsed successfully      7
enterprise shell scripts syntax checked     passed
```

The visible development service on port `8020` intentionally runs with:

```text
AUTH_MODE                         disabled
POSTGRES_RLS_MODE                 off
STORAGE_BACKEND                   local
telemetry                         disabled
provider                          qwen:qwen-plus
```

It validates local behavior only. It is not enterprise deployment evidence.

## Findings fixed during this audit

### Release evidence could be bound to the wrong source

The release report previously recorded `git rev-parse HEAD` without rejecting
uncommitted changes. A dirty source tree could therefore be tested while the
report claimed the previous commit.

The release gate now fails closed unless `git status --porcelain` is empty. It
records only a count, status codes and a digest, not local filenames.

### Dependency-audit failure message was misleading

A transient `pip-audit` command failure with valid empty JSON was summarized as
"found 0 issues" even though the gate correctly failed.

The summary now distinguishes command failure, parse failure and actual
vulnerability findings. Error output is represented only by a digest.

### Destructive acceptance candidate reuse was unclear

The staging verifier revokes its candidate membership. Revocation is
intentionally terminal, so the same candidate cannot be reused.

The verifier now fails at an explicit `candidate_membership_unused` precondition
and instructs operators to use a fresh isolated database or a newly provisioned
candidate. The membership lifecycle was not weakened to make reruns pass.

### Current architecture version text was stale

The v0.9 enterprise platform overview still described the package as
`0.8.0.dev0`. It now identifies the implemented research package as
`0.9.0.dev0` and reserves `0.9.0rc1` for an accepted external gate.

## Migration interpretation

The complete migration chain succeeds on a fresh SQLite database. Running
`alembic check` against SQLite reports PostgreSQL-only foreign keys, partial
indexes, composite constraints and RLS-related metadata as differences. That
SQLite output is not accepted as PostgreSQL parity evidence.

The authoritative `postgres_migration` gate remains blocked until the enterprise
Compose rehearsal runs against PostgreSQL 17 with the separate migration and
runtime roles.

## Remaining release blockers

The following sanitized evidence artifacts are still required:

1. `tenant-isolation.json`
2. `auth-token-matrix.json`
3. `route-capability-coverage.json`
4. `postgres-migration.json`
5. `storage-contract.json`
6. `queue-idempotency.json`
7. `audit-redaction.json`
8. `telemetry-redaction.json`
9. `disaster-recovery.json`
10. `ai-regression.json`
11. `staging-observation.json`
12. `enterprise-ui-acceptance.json`

The current Windows host has no Docker CLI, and the connected SeetaCloud
container has no Docker daemon or Compose plugin. Container-level PostgreSQL,
MinIO and disaster-recovery validation must therefore run on the intended Vultr
Docker host.

The in-app browser automation runtime also could not initialize because its local
kernel asset path was unavailable. Static delivery, syntax and HTTP behavior
passed, but new desktop/mobile visual screenshots were not produced.

## Recommended next action

Deploy commit `08408234d33010834a15225689101e0c8054dc52` or a descendant containing
only this report to an isolated Vultr staging host. Run the enterprise Compose
verification and recovery scripts, collect the 12 sanitized artifacts, observe
the deployment for at least 24 hours, and rerun:

```bash
uv run ai-examiner-verify-v09-release \
  --require-release-ready \
  --output data/release-evidence/v0_9-release-gate.json
```

Only a `release_ready` result permits promotion to `0.9.0rc1`.
