# AI Examiner v0.9.0

AI Examiner v0.9.0 is the first final enterprise-platform release. It combines the
active-questioning, adaptive assessment, long-term learner intelligence, scenario
templates, multimodal evidence and realtime voice capabilities with organization
tenancy and production governance.

## Enterprise capabilities

- OIDC authentication, organization switching and capability-based RBAC;
- PostgreSQL Row-Level Security with least-privilege runtime identities;
- local and S3-compatible tenant object storage;
- durable tenant-aware Celery jobs with idempotency and recovery;
- append-only audit, model allowlists, quotas, rate limits and cost ownership;
- retention, export, legal hold, deletion and human-review workflows;
- OpenTelemetry readiness and recoverable single-host deployment tooling;
- dedicated enterprise administration UI.

## Final acceptance

```text
Full automated suite           352 passed
Release gate                   23 passed / 0 failed / 0 blocked
PostgreSQL RLS                 48 policies / 41 protected tables
Real provider                  qwen:qwen-plus
Template evidence              7 templates / 210 cases
Independent RC2 observation    24 hours / 1,440 samples / 0 failures
Availability                   100%
TLS and OIDC                   verified
Open release blockers          0
```

The independent observation exercised commit `bd6dc19`. The final promotion changes
only version surfaces, static cache identifiers, documentation and accepted evidence;
it does not alter runtime business behavior.

## Deployment

Deploy the immutable tag `v0.9.0` or track `main`. Preserve `.env`, database, object
storage and user uploads during upgrades. See
`docs/deployment/V0_9_OPERATOR_MANUAL.md` for exact upgrade, backup and rollback steps.
