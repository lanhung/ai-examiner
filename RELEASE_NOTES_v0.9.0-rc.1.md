# AI Examiner v0.9.0-rc.1 Release Notes

Status: release candidate. The v0.9 release gate reported `release_ready` with
23 passed checks, zero failures and zero blocks.

## Enterprise platform

- PostgreSQL parity and tenant ownership propagation;
- organization, principal and membership model;
- OIDC authorization-code flow with PKCE and strict access-token validation;
- capability RBAC and object-level authorization;
- PostgreSQL forced RLS;
- local and S3-compatible private storage;
- tenant-aware idempotent jobs with leases, cancellation and recovery;
- append-only audit evidence;
- organization model policy, rate limits, quotas and usage ledger;
- retention, export, deletion and human-review workflows;
- OpenTelemetry, Prometheus and Grafana operations profile;
- recoverable single-host enterprise Docker Compose deployment;
- enterprise administration interface.

## Release hardening

- machine-readable deterministic and staging release gates;
- dependency vulnerability and tracked-source secret scans;
- real-provider governance probe without prompt or response retention;
- migration-head and route-policy verification;
- preserved v0.8 Planner v6 behavior evidence;
- enterprise operator and evidence manuals.

## Upgrade

Follow:

```text
docs/deployment/V0_9_OPERATOR_MANUAL.md
```

The release uses additive migrations. Back up PostgreSQL and object storage before
upgrade. Do not run `docker compose down -v`.

## Acceptance evidence

- 24-hour HTTPS/OIDC observation: 1,441 samples, zero failures, 100% availability;
- maximum health/readiness sampling latency: 167 ms;
- desktop and mobile enterprise UI acceptance with OIDC login;
- PostgreSQL RLS, S3-compatible storage, Redis idempotency and disaster recovery;
- real Qwen Plus model-governance and frozen seven-template AI regression evidence.

## Candidate boundary

RC1 is approved for controlled staging. It is not the final `0.9.0` production
release. Production deployments must enable and validate the intended PostgreSQL
RLS, object-storage and telemetry profiles instead of inferring those settings from
the lightweight AutoDL compatibility target.
