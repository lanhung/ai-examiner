# v0.7 Long-term Memory API Draft

Status: Research contract, not implemented  
Version: 0.7.0-draft.1

## 1. Contract rules

- Existing v0.5 and v0.6 endpoints remain backward compatible.
- All identifiers are opaque UUIDs.
- Every write supports an `Idempotency-Key` header.
- Every aggregate response includes `algorithm_version` and `rebuilt_at`.
- Predicted values are labeled separately from observed values.
- Memory-disabled identities reject durable writes with `409 memory_disabled`.
- Cross-project reads require a confirmed identity link.
- Until authentication exists, the API is evaluation-only behind an operator access
  boundary.

Error envelope:

```json
{
  "error": {
    "code": "concept_mapping_unconfirmed",
    "message": "The knowledge unit is not mapped to an accepted concept.",
    "details": {}
  }
}
```

## 2. Learner identity

### `POST /api/learner-identities`

Creates an opaque memory identity.

```json
{
  "external_subject_ref": "local-test-user-01",
  "display_name": "Optional local label",
  "memory_enabled": false,
  "memory_scope": "project_only"
}
```

The server hashes `external_subject_ref`; it never returns or logs the raw value.

### `POST /api/learner-identities/{identity_id}/links`

Links an existing project-scoped `LearnerSubject` after explicit confirmation.

```json
{
  "learner_subject_id": "uuid",
  "status": "confirmed",
  "provenance": "explicit"
}
```

Revocation uses `DELETE` on the returned link resource. Revocation stops future
cross-project aggregation and triggers rebuild; it does not delete project-local
assessment records.

## 3. Memory settings

### `PATCH /api/learner-identities/{identity_id}/memory-settings`

```json
{
  "memory_enabled": true,
  "memory_scope": "linked_projects",
  "preference_inference_enabled": false,
  "retest_planning_enabled": true,
  "retention_days": 365
}
```

Changing scope creates a `memory_control` event and queues an aggregate rebuild.

## 4. Memory inspection

### `POST /api/learner-identities/{identity_id}/memory/import`

Imports eligible existing assessment evidence through accepted `exact` or `narrower`
concept mappings. `dry_run=true` reports eligible rows without writing. Repeating an
import is idempotent.

### `GET /api/learner-identities/{identity_id}/memory`

Filters:

```text
category
concept_id
project_id
from
to
include_superseded=false
cursor
limit
```

Response items contain source references, status, policy version and expiry. Raw
audio and unrestricted transcript summaries are never returned because they are not
allowed memory categories.

### `GET /api/learner-identities/{identity_id}/growth`

```json
{
  "concepts": [
    {
      "concept_id": "uuid",
      "title": "Experimental validity",
      "last_observation": {
        "mastery": 0.72,
        "confidence": 0.68,
        "observed_at": "2026-07-20T08:00:00Z"
      },
      "current_prediction": {
        "retention": 0.61,
        "confidence": 0.43,
        "algorithm_version": "fixed-half-life-v1",
        "predicted_at": "2026-08-10T08:00:00Z"
      },
      "series": []
    }
  ]
}
```

The API must never return a predicted value in an `observed_mastery` field.

## 5. Concept mappings

### `GET /api/concepts`

Searches the canonical registry by namespace, key or text.

### `POST /api/knowledge-units/{knowledge_unit_id}/concept-mappings`

Creates a proposed mapping with evidence. Model proposals cannot set `accepted`.

### `PATCH /api/concept-mappings/{mapping_id}`

Accepts or rejects the proposal. Any acceptance that changes existing longitudinal
state queues a rebuild and records the reviewer type.

## 6. Retest plans

### `POST /api/learner-identities/{identity_id}/retest-plans`

```json
{
  "horizon_days": 14,
  "max_items": 8,
  "mode": "shadow",
  "project_id": null
}
```

Response items include:

```json
{
  "concept_id": "uuid",
  "due_at": "2026-07-28T00:00:00Z",
  "priority": 0.81,
  "reason_code": "unresolved_misconception",
  "predicted_retention": 0.58,
  "uncertainty": 0.31,
  "source_state_version": "long-state-v1"
}
```

`mode=active` is rejected until the release feature flag and evaluation gate are
both enabled.

### `GET /api/learner-identities/{identity_id}/retest-plans`

Returns plans and outcomes. Filters include status, date range and concept.

## 7. Preferences

### `GET /api/learner-identities/{identity_id}/preferences`

Returns explicit, proposed, active, rejected and expired entries with provenance.

### `PATCH /api/learner-identities/{identity_id}/preferences/{preference_id}`

```json
{
  "action": "confirm",
  "value": "example_first"
}
```

Actions:

```text
confirm
reject
edit
expire
```

Preferences affect interaction only and are excluded from assessment scoring
payloads.

## 8. Rebuild

### `POST /api/learner-identities/{identity_id}/memory/rebuild`

```json
{
  "algorithm_version": "fixed-half-life-v1",
  "dry_run": true
}
```

Dry-run response compares old and rebuilt aggregates without replacing active
state. Non-dry-run rebuilds must be idempotent and preserve the prior version until
success.

## 9. Export

### `POST /api/learner-identities/{identity_id}/memory/export`

```json
{
  "format": "json",
  "include_source_quotes": false
}
```

Returns a background job. The downloaded export has a short expiry and is removed
when the corresponding memory is deleted.

## 10. Deletion

### `DELETE /api/learner-identities/{identity_id}/memory`

```json
{
  "scope": "concept",
  "concept_id": "uuid",
  "confirmation": "delete"
}
```

Scopes:

```text
preference
concept
project_link
all_long_term_memory
identity_and_memory
```

The response is a deletion job. While pending, new writes to the affected scope are
blocked. Completion reports row categories and counts without returning deleted
content.

## 11. Audit and observability

Administrative evaluation endpoints may expose aggregate counts and timing, but
must not expose external subject references, raw keys, answer text or provider
credentials.

Required metrics:

```text
memory_candidate_total{category,status}
concept_mapping_total{status,source}
memory_rebuild_seconds{algorithm_version}
retest_plan_items_total{reason_code,mode}
memory_export_jobs_total{status}
memory_deletion_jobs_total{status,scope}
cross_identity_access_denied_total
```
