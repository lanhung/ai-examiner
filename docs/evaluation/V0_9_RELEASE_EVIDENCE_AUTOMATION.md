# v0.9 Release Evidence Automation

## Purpose

This workflow turns the v0.9 release checklist into machine-verifiable, sanitized
evidence. It does not allow an operator to promote a release by creating JSON files
that only say `passed`.

## Deterministic and integration evidence

Run from the repository root in an environment with Redis and an S3-compatible
service:

```bash
python -m ai_examiner.release_evidence \
  --redis-url redis://127.0.0.1:6379/15 \
  --s3-endpoint-url http://127.0.0.1:9000 \
  --s3-region us-east-1 \
  --s3-bucket ai-examiner-release \
  --s3-access-key "$S3_ACCESS_KEY_ID" \
  --s3-secret-key "$S3_SECRET_ACCESS_KEY"
```

The command runs focused OIDC, authorization, storage, queue, audit, telemetry and
AI regression suites. It additionally performs:

- a concurrent Redis `SET NX` admission probe;
- an actual S3 put, head, get, presign and verified delete probe;
- an OTLP/HTTP export with canary attributes removed before serialization.

Raw pytest output, credentials, URLs and model content are not stored. Command output
is represented by a SHA-256 digest.

## Host PostgreSQL disaster recovery

AutoDL does not expose a usable Docker daemon. Use the host-equivalent isolated
restore rehearsal:

```bash
python -m ai_examiner.recovery_evidence \
  --database-url "$ENTERPRISE_MIGRATION_DATABASE_URL" \
  --object-root /path/to/data/objects
```

The command creates a custom-format PostgreSQL dump, restores it into a randomly
named temporary database, compares every public table count, copies and verifies all
object hashes, drops the temporary database and confirms the source is still
readable. The dump and restored objects are deleted before the sanitized result is
written.

## Twenty-four hour observation

The observation target must use HTTPS and OIDC. Start it under `screen`, `tmux` or
`nohup`:

```bash
nohup python -m ai_examiner.staging_observer \
  --base-url https://staging.example.com \
  --duration-hours 24 \
  --interval-seconds 60 \
  >data/release-evidence/staging-observer.log 2>&1 &
```

The observer writes resumable state outside the tracked evidence directory. It only
produces `status: passed` after 24 elapsed hours with zero failed health/readiness
samples, successful TLS, OIDC readiness and zero declared release blockers.

## Promotion check

After an operator reviews and moves accepted artifacts into
`docs/evaluation/evidence/v0_9/`, run:

```bash
python -m ai_examiner.release_hardening --require-release-ready
```

The verifier rejects malformed schema versions, placeholder evidence, insufficient
token matrices, fake S3/Redis results, leakage, missed RPO/RTO objectives, an
observation shorter than 24 hours and incomplete enterprise UI acceptance.
