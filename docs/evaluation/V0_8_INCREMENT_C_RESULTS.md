# v0.8 Increment C Session Binding Results

## Scope

Increment C completes WP-05: text and realtime voice sessions can bind to a
published scenario-template version and retain the exact effective policy used when
the session was created.

This is a development increment on `develop/v0.8.0`, not a release candidate.

## Resolution contract

New sessions resolve templates in this order:

```text
explicit session template
-> active project default
-> legacy mode mapping
-> unbound legacy session when no mapping exists
```

Override precedence is:

```text
template defaults
-> project default overrides
-> session template_overrides
-> explicitly supplied legacy request fields
```

Only active templates with a published, compiled version are selectable. A mode
conflict, undeclared override or invalid override fails before provider lookup or
model execution.

## Persisted replay artifact

Alembic revision `20260723_0007` adds the following nullable fields to
`exam_sessions`:

```text
template_version_id
template_snapshot_json
template_fingerprint
template_compiler_version
template_overrides_json
```

The snapshot is deep-copied from deterministic compiler output. Session inspection
recomputes its SHA-256 fingerprint and reports `verified`,
`fingerprint_mismatch`, `missing_artifact` or `not_applicable`.

Existing sessions remain readable with null fields. Downgrade refuses to remove the
columns after any session is bound, preserving auditability.

## Compatibility version

`academic.thesis_defense@1.1.0` adds a declared bounded
`max_followups_per_question` override. The published v1.0 source is not edited.
Startup seeds both versions idempotently and legacy defense sessions select the
latest published semantic version.

## Behavioral verification

The test suite verifies:

- existing text request bodies resolve the latest defense compatibility template;
- project defaults apply only when the request does not explicitly override them;
- draft versions and invalid overrides cannot create sessions;
- equivalent text and OpenAI voice policy inputs produce the same fingerprint;
- Qwen safety clamps are represented in the stored snapshot;
- teaching mode remains an unbound legacy session until its compatibility template
  is delivered;
- stored snapshot tampering is detected;
- v0.7 data survives migration upgrade, downgrade and re-upgrade while no bound
  session exists.

## Results

```text
session binding tests                 7 passed
targeted template/text/voice tests   38 passed
full pytest                          90 passed
full Ruff                            passed
Alembic single head                  20260723_0007
SQLite migration round trip          passed
```

The Windows test process prints the pre-existing AnyIO `TestClient` shutdown
access-violation diagnostic after all assertions complete. Pytest exits with code
zero; no test is reported failed.

Docker Compose was not available on this host, so container build and Vultr
migration rehearsal remain release-gate work.

## Held work

Increment C does not yet make template objectives, action allowlists, assessment
dimensions or report sections control runtime Agent behavior. Those are WP-06,
WP-07 and WP-08 and must be delivered as separate reviewable increments.
