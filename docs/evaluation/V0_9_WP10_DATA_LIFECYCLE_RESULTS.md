# v0.9 WP-10 Data Lifecycle Evaluation

Status: implemented and locally verified

## Scope

The WP-10 suite verifies:

- retention policy versioning and canonical digest;
- scoped legal-hold creation and human release;
- export manifests, checksums, object inclusion and authorized download;
- independent deletion approval;
- legal-hold blocking and post-release retry;
- relational and object-storage deletion convergence;
- protected audit evidence after target deletion;
- human review decisions and appeals;
- model-authored final-decision rejection;
- append-only review events;
- migration creation and guarded downgrade.

## Security invariants

1. A project requester cannot approve the same destructive request.
2. An active organization or target hold prevents storage mutation.
3. An export file is resolved by artifact ID, never by a caller-supplied key.
4. Download authorization is evaluated again when the file is requested.
5. Export and decision idempotency keys cannot be reused with different data.
6. Project deletion reports completion only after SQL and object checks converge.
7. Audit and model-usage evidence survives target deletion.
8. AI may create review evidence but cannot create a final decision event.

## Commands

```bash
uv run pytest -q tests/test_data_lifecycle_v09.py
uv run pytest -q tests/test_job_hardening_v09.py tests/test_audit_system_v09.py
uv run ruff check .
uv run alembic heads
```

## Current result

Focused lifecycle/job/audit verification:

```text
25 passed
```

Full SQLite and PostgreSQL CI results are recorded at the WP-10 branch commit after
publication. Windows may print a CPython asyncio proactor teardown access-violation
message after pytest has already returned exit code zero; this is not an application
test failure.
