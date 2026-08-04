# AI Examiner v0.9.0-rc.1 Release Notes

Status: draft. The release candidate and tag do not exist until the v0.9 release
gate reports `release_ready`.

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

## Known promotion holds

- the in-progress 24-hour HTTPS/OIDC staging observation;
- desktop/mobile enterprise UI browser evidence.

The real-provider governance probe, OIDC token matrix, PostgreSQL/RLS checks,
S3-compatible storage contract, Redis idempotency, telemetry redaction and
database/object recovery rehearsal have passed. Interactive OIDC login and stale
tenant protection have also passed at the HTTP/session boundary; visual browser
acceptance remains separate and must not be inferred from those API checks.

These holds must be cleared before creating `v0.9.0-rc.1`.
