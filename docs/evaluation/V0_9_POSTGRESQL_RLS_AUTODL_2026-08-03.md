# AI Examiner v0.9 PostgreSQL and RLS AutoDL Acceptance

Date: 2026-08-03  
Branch: `research/v0.9.0`  
Tested source commit: `398a41f738adcffddbe1549d605265c2bb39f951`

## Scope

This acceptance validates the v0.9 PostgreSQL schema, migration chain, least-
privilege runtime identity and PostgreSQL row-level tenant isolation on the
AutoDL staging host. It does not migrate or modify the live port-6006 SQLite
database.

The host cannot run the enterprise Docker topology because its container lacks
`CAP_NET_ADMIN`. PostgreSQL was therefore installed directly on the host and
bound to loopback only.

## Environment

```text
Operating system       Ubuntu 22.04.5 LTS
Target database        PostgreSQL 17.10
Target port            127.0.0.1:5433
Database encoding      UTF8
Database collation     C.UTF-8
Test database          examiner_v09_test
Live application       SQLite on port 6006, unchanged
```

PostgreSQL 14.23 was first installed from the Ubuntu repository and used for a
complete preliminary proof. PostgreSQL 17.10 was then installed from the
official PostgreSQL PGDG repository so the final evidence matches the enterprise
Compose target major version.

The first PostgreSQL 17 cluster inherited `SQL_ASCII` from the container locale.
Because this is unsafe for Chinese and multilingual content, the empty cluster
was immediately recreated with explicit `UTF8` encoding and `C.UTF-8` locale
before any application migration ran.

## Migration result

All 16 additive Alembic revisions migrated successfully from an empty database:

```text
base
  -> 20260716_0001
  -> 20260720_0002
  -> 20260721_0003
  -> 20260721_0004
  -> 20260721_0005
  -> 20260723_0006
  -> 20260723_0007
  -> 20260727_0008
  -> 20260727_0009
  -> 20260728_0010
  -> 20260728_0011
  -> 20260728_0012
  -> 20260728_0013
  -> 20260728_0014
  -> 20260728_0015
  -> 20260728_0016 (head)
```

## RLS result

The repository verifier `deploy/verify-v09-rls.py` passed on PostgreSQL 17:

```text
tenant policies                    48
required protected tenant tables  41
rows visible without context       0
organization A project rows        1
organization B project rows        1
cross-tenant write blocked         yes
audit UPDATE blocked               yes
audit DELETE blocked               yes
review-event UPDATE blocked        yes
review-event DELETE blocked        yes
```

The real application login was verified separately from the migration account:

```text
superuser                          false
CREATEROLE                         false
CREATEDB                           false
BYPASSRLS                          false
missing-context rows               0
20-worker tenant reads             100 / 100 passed
cross-tenant INSERT                rejected
```

## Regression result

The complete application suite was executed against both PostgreSQL 14 and the
target PostgreSQL 17 database:

```text
PostgreSQL 14.23                   331 / 331 passed in 299 seconds
PostgreSQL 17.10                   331 / 331 passed in 260 seconds
```

The first PostgreSQL run exposed a test-isolation defect: the readiness test
inherited `MODEL_RATE_LIMIT_BACKEND=memory` from the staging `.env`. Tests now
set the expected backend explicitly, making the suite independent of deployment
configuration. This was a test reliability defect, not an RLS failure.

## Operational boundary

The PostgreSQL clusters are test-only and are not used by the live v0.9 process.
Credentials are stored outside the repository in root-only files with mode 600.
No password, API key, user document, transcript or raw database dump is included
in release evidence.

AutoDL does not run systemd as its normal init process. After an instance reboot,
the PostgreSQL 17 test cluster can be restored with:

```bash
pg_ctlcluster 17 main start
pg_isready -h 127.0.0.1 -p 5433
```

## Remaining production boundary

This result satisfies the native PostgreSQL migration and tenant-isolation proof.
It does not yet prove the complete enterprise Docker Compose topology, Redis and
Celery recovery, MinIO object recovery, real OIDC, OTLP export, or coordinated
database/object disaster recovery.
