# v0.9 Release Evidence Contract

This directory contains sanitized release evidence, not raw logs, prompts, documents,
transcripts, tokens, credentials or database dumps.

Every JSON artifact requires:

```json
{
  "schema_version": "1.0",
  "generated_at": "ISO-8601 UTC timestamp",
  "source_commit": "40-64 lowercase hexadecimal Git object ID",
  "status": "passed"
}
```

Required files:

```text
tenant-isolation.json
auth-token-matrix.json
route-capability-coverage.json
postgres-migration.json
storage-contract.json
queue-idempotency.json
audit-redaction.json
quota-model-policy.json
telemetry-redaction.json
disaster-recovery.json
ai-regression.json
staging-observation.json
enterprise-ui-acceptance.json
```

## Specialized fields

`quota-model-policy.json`:

```json
{
  "actual_provider": "qwen",
  "actual_model": "qwen-plus",
  "ledger_status": "completed",
  "provider_result_matches_ledger": true,
  "prompt_content_recorded": false,
  "response_content_recorded": false,
  "api_key_recorded": false
}
```

`disaster-recovery.json`:

```json
{
  "rpo_seconds": 0,
  "rto_seconds": 120,
  "object_restore_verified": true,
  "rollback_success": true
}
```

`staging-observation.json`:

```json
{
  "observation_hours": 24,
  "open_release_blockers": 0,
  "tls_verified": true,
  "oidc_verified": true
}
```

`enterprise-ui-acceptance.json`:

```json
{
  "desktop_passed": true,
  "mobile_passed": true,
  "oidc_login_passed": true,
  "stale_tenant_guard_passed": true
}
```

The release verifier rejects missing, malformed, incomplete or non-passing evidence.
An operator must review generated files before committing them.

