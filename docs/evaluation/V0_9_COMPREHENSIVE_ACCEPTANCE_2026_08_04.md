# v0.9 Comprehensive Acceptance

Date: 2026-08-04  
Branch: `research/v0.9.0`  
Starting commit: `d3eacdd`  
Package version: `0.9.0.dev0`

## Decision

The deployed research build passed the available application, real-provider and
native PostgreSQL acceptance checks. One dependency vulnerability was found and
fixed during the run. Release-candidate promotion remains held because the full
external enterprise evidence set is not yet present.

## Public runtime baseline

The primary AutoDL mapping served the current v0.9 process on local port `6006`.
The health payload reported Qwen `qwen-plus` as configured and ready. The root,
enterprise console, health, readiness, provider catalog, template health, voice
configuration and OpenAPI endpoints all returned HTTP 200. Application and
acceptance logs contained no traceback or server error.

## Isolated real-Qwen acceptance

A fresh SQLite database and isolated object directories were used so membership,
retention, legal-hold and deletion tests could not modify the deployed data.

```text
HTTP acceptance checks                  48
passed                                  48
failed                                   0
Qwen async enqueue                      30 ms
health during generation                 6 ms
Qwen terminal completion           117,582 ms
duplicate idempotency reuse             passed
```

The run covered enterprise context and capabilities, authentication denial,
cross-organization concealment, membership lifecycle, model policy, quota,
projects, document upload, evidence downloads, real Qwen blueprint generation,
usage exports, retention, organization export integrity, legal hold, dual control,
verified deletion, human review, appeals, job recovery, append-only audit export,
template health and voice provider configuration.

## PostgreSQL and RLS

PostgreSQL 17.10 was started on port `5433` and the disposable `_test` database
was recreated through the complete Alembic chain.

```text
Alembic revisions applied               16
protected tenant tables                 41
RLS policies                            48
missing-context visible rows             0
cross-tenant write                      blocked
runtime concurrent reads           100/100
runtime BYPASSRLS                       false
runtime superuser/create role/db        false
audit update/delete                     blocked
human-review update/delete              blocked
```

## Regression and security

```text
Ruff                                    passed
JavaScript syntax (app + enterprise)    passed
pytest collected                        337
pytest last-failed cache                 empty
tracked-source secret scan              passed
Alembic heads                            1
protected route policies                48
frozen Planner v6 evidence              passed
```

The first dependency audit found `CVE-2026-69247` in `cryptography 49.0.0`.
The project now requires `cryptography>=50.0.0,<51.0`, the lock file resolves
50.0.0, and the repeated `pip-audit` run reports no known vulnerabilities.
Focused OIDC, authorization and release-hardening tests passed after the upgrade.

## Availability probe

A 20-worker probe sent 160 requests across the public root, enterprise console,
health, readiness, providers, template health, voice configuration and OpenAPI
endpoints.

```text
requests                               160
HTTP failures                            0
median latency                       838 ms
p95 latency                         1,964 ms
maximum latency                     2,548 ms
```

This probe includes new TLS connections through the AutoDL public mapping and is
an availability smoke test, not a sustained capacity benchmark. Direct sequential
requests were normally 2-13 ms, except template-health at about 245-258 ms.

## Browser and audio limitation

The Codex in-app browser control runtime failed before it could attach to the open
tab (`failed to write kernel assets`, local path unavailable). Therefore this run
does not claim new click-by-click screenshots, responsive layout acceptance, real
microphone capture, speaker playback or WebRTC acoustic quality. HTTP delivery,
static assets, JavaScript syntax and voice configuration passed, but browser and
physical audio acceptance must be rerun when browser control is available.

## Remaining external release evidence

- real OIDC provider login, token rejection matrix and JWKS rotation;
- Redis-backed quota concurrency and worker restart recovery;
- real S3/MinIO migration, authorized download and restore;
- OpenTelemetry collector outage and redaction verification;
- enterprise disaster-recovery rehearsal;
- desktop/mobile browser screenshots and real microphone/WebRTC audio;
- 24-hour staging observation with no open release blockers.

These gaps keep the package at `0.9.0.dev0`; no release-candidate tag is authorized
by this acceptance run.
