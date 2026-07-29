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

- Vultr staging observation;
- real OIDC browser acceptance;
- desktop/mobile enterprise UI evidence;
- real-provider governance evidence;
- complete MinIO recovery and rollback artifact set.

These holds must be cleared before creating `v0.9.0-rc.1`.

