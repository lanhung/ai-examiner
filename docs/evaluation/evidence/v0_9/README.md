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

`status: passed` alone is never sufficient. The release verifier validates
specialized measurements for every security-sensitive artifact. Generate evidence
with the project CLIs and review it before committing:

```bash
ai-examiner-generate-v09-evidence \
  --redis-url redis://127.0.0.1:6379/15 \
  --s3-endpoint-url http://127.0.0.1:9000 \
  --s3-bucket ai-examiner-release \
  --s3-access-key "$S3_ACCESS_KEY_ID" \
  --s3-secret-key "$S3_SECRET_ACCESS_KEY"
```

The generated files contain counts, booleans and hashes only. They must not contain
tokens, provider content, uploaded documents, database URLs or object contents.

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

Additional mandatory measurements include:

- OIDC: at least ten invalid-token cases, JWKS cache/rotation and PKCE;
- authorization: exact protected-route registry and OpenAPI metadata coverage;
- storage: local plus a real S3-compatible endpoint and verified deletion;
- queue: a real Redis endpoint plus zero duplicate billable outcomes;
- audit and telemetry: zero canary leakage and failure isolation;
- AI regression: seven templates, at least 210 frozen cases and a real-provider probe.

The release verifier rejects missing, malformed, incomplete or non-passing evidence.
An operator must review generated files before committing them.
