# v0.9 SeetaCloud Direct-Process Deployment Rehearsal

Date: 2026-07-29

Status: passed as a compatibility staging rehearsal; not accepted as the v0.9
enterprise deployment gate.

## Scope

The `research/v0.9.0` branch at commit
`a0b01c2b40649bc93bdf45065808c51e4d36b322` replaced the existing v0.5 process
on port `6008`.

The available host is a SeetaCloud container. A Docker client is installed, but
the host does not expose a Docker daemon. The deployment therefore used the
repository's direct-process startup script instead of the enterprise Compose
profile.

This rehearsal validates:

- backward-compatible migration of the existing SQLite database;
- preservation of uploaded and generated local objects;
- worktree-aware direct-process startup;
- Qwen Plus provider readiness and a bounded real-provider call;
- the public application, enterprise UI and core API surfaces;
- rollback data and process metadata capture.

It does not validate:

- Vultr networking or firewall behavior;
- PostgreSQL row-level security;
- Redis-backed rate limiting and Celery delivery;
- MinIO or S3 object storage;
- OIDC login and strict access-token validation;
- Caddy TLS or the observability overlay;
- multi-container disaster recovery;
- the required 24-hour staging observation.

## Migration

The old service reported `0.5.0rc4` and used the v0.5 `data-v05` database. The
service was stopped before the final copy. Alembic upgraded the copied database
from `20260716_0001` to the single head `20260728_0016`.

Post-migration data counts:

```text
projects          6
documents         6
exam_sessions     3
organizations     1
principals        0
```

Authentication remains disabled for this legacy single-user staging data. The
deployment runs with local storage and in-memory model rate limiting.

## Verification

```text
GET /health                200
GET /ready                 ready
GET /                      200
GET /enterprise            200
GET /api/providers         200
OpenAPI paths              116
Alembic current/head       20260728_0016 / 20260728_0016
Runtime source commit      a0b01c2b40649bc93bdf45065808c51e4d36b322
Runtime worktree           ai-examiner-v0.9-staging
```

The bounded Qwen Plus governance probe passed:

```text
provider/model             qwen / qwen-plus
input tokens               126
output tokens              6
latency                    514 ms
estimated cost             USD 0.00001565
ledger match               yes
prompt retained            no
response retained          no
API key retained           no
```

The sanitized machine-readable provider artifact is stored as
`docs/evaluation/evidence/v0_9/quota-model-policy.json`.

## Backup And Rollback

The cutover backup is:

```text
/root/autodl-tmp/ai-examiner-mvp/backups/
  cutover-v05-to-v09-20260729T081907Z
```

It contains the prior `.env`, `data-v05`, local object data and the old process
executable, working directory, PID and Git commit metadata. Secrets and user data
from this backup are intentionally not committed to Git.

If the new process fails, stop the listener on port `6008`, restore `.env`,
`data-v05` and `data` from the backup, and start Uvicorn from the recorded old
working directory and executable.

## Release Decision

The rehearsal is useful staging evidence but does not satisfy any missing
enterprise release artifact by itself. The package remains `0.8.0.dev0`, the
branch remains `research/v0.9.0`, and no v0.9 release-candidate tag is authorized.

## Runtime correction and optimization deployment

During the 2026-07-30 optimization deployment, process inspection found that the
listener on port `6008` had been restarted with a Python path and current working
directory from the previous v0.5 worktree, despite the earlier source verification
record. The process still served compatible data, but it was not an acceptable
source-of-truth deployment.

The listener was stopped and restarted from:

```text
/root/autodl-tmp/ai-examiner-mvp/ai-examiner-v0.9-staging
```

The corrected runtime now uses commit:

```text
e2713368dd409deb4a460dee07906d8e6db763f3
```

The existing `.env` and `data-v05` state were preserved. A pre-deployment backup
was created at:

```text
/root/autodl-tmp/ai-examiner-mvp/backups/
  pre-blueprint-async-20260730T093112Z
```

After correction, `/health` and `/ready` passed, the real Qwen Plus asynchronous
blueprint job completed, and the isolated 45-workflow acceptance suite passed.
This correction strengthens the direct-process evidence but does not turn the host
into an enterprise Compose environment.
