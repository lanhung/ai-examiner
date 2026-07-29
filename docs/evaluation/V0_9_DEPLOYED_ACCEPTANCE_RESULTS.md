# v0.9 Deployed Acceptance Results

Date: 2026-07-29

Branch: `research/v0.9.0`

Tested source: `89bc6a6decde7082e535eb18ba103522d1507206`

Status: direct-process staging acceptance passed; enterprise release promotion
remains held.

## Test strategy

The live v0.9 research process continued to serve the migrated v0.5 data on port
`6008`. Destructive acceptance ran on port `6011` with a fresh SQLite database,
isolated object directories and generated test principals. No production project,
document, identity or policy was modified.

The acceptance runner is:

```text
deploy/verify-v09-direct-staging.py
```

## Results

The isolated HTTP acceptance completed:

```text
tests                45
passed               45
failed               0
server exceptions    0
```

Validated workflows:

- health, readiness and enterprise UI assets;
- identity context and capability registry;
- unauthenticated denial and cross-membership denial;
- membership create, optimistic update and revoke;
- model allowlist and quota updates;
- project creation, Markdown upload and page evidence;
- authorized document and evidence downloads;
- real Qwen Plus blueprint planning;
- usage dashboard and redacted NDJSON export;
- retention policy and organization ZIP export;
- legal hold, dual-control denial and verified deletion;
- human review assignment, decision and appeal;
- job listing and recovery;
- append-only audit listing and NDJSON export;
- template health and realtime voice provider configuration.

## Real provider behavior

The real Qwen Plus Planner returned `201` and created grounded questions. The call
took `153,742 ms`, which is functionally correct but too slow for an interactive
request. This should be moved behind the existing asynchronous job path or receive
a stricter provider timeout and progress UI before release.

The run recorded no prompts, responses or API keys.

## Defect found and fixed

The enterprise policy UI documents public task names such as `planner`, but runtime
planning uses the internal Agent name `session_planner`. A narrow policy that
allowed `planner` therefore denied a real blueprint request before contacting
Qwen.

The governance matcher now maps:

```text
planner   -> session_planner
analyzer  -> answer_analyzer
reporter  -> report_generator
```

An automated regression test protects this contract.

## Automated regression

After the fix:

```text
Ruff                       passed
full local pytest          passed
GitHub enterprise Compose  passed on the prior deployed source
GitHub PostgreSQL           passed on the prior deployed source
```

The Windows test process still prints the known AnyIO shutdown access-violation
diagnostic after reporting 100 percent completion, but exits with code zero. Linux
GitHub CI remains authoritative.

## Remaining release blockers

This host does not expose a Docker daemon, so the following v0.9 release evidence
is still unavailable:

- Vultr enterprise Compose deployment;
- PostgreSQL RLS under the runtime role;
- Redis-backed concurrent quota and worker restart recovery;
- MinIO/S3 migration and restore on the staging host;
- real OIDC login, JWKS rotation and invalid-token matrix;
- Caddy TLS and mobile/desktop UI screenshots;
- OpenTelemetry collector outage and dashboard observation;
- isolated disaster recovery rehearsal;
- 24-hour staging observation.

This result does not authorize `0.9.0rc1`.
