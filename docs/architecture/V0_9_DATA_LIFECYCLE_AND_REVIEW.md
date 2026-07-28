# v0.9 Data Lifecycle and Human Review

Status: WP-10 implemented on `research/v0.9.0`

## 1. Objective

WP-10 turns retention, export, deletion and review into one tenant-scoped control
plane. A destructive operation is not complete when an SQL `DELETE` returns. It is
complete only when:

1. the request was authorized and independently approved;
2. no applicable legal hold is active;
3. relational content is gone;
4. every controlled object is absent from the active storage backend;
5. verification evidence is committed with the request;
6. immutable audit and model-usage evidence remains available.

## 2. Data model

### `OrganizationRetentionPolicy`

One versioned policy per organization:

- monitor or enforce mode;
- project, session, document and learner-memory periods;
- export artifact lifetime;
- deletion grace period;
- canonical SHA-256 policy digest;
- last human updater.

Changing the policy increments its version. Runtime defaults are conservative and
do not automatically erase historical content.

### `LegalHold`

An active hold can cover:

- the organization;
- a project;
- a learner identity;
- a specific data-subject request.

Deletion evaluates organization and target-specific holds immediately before any
storage mutation. Release records the releasing principal, reason and time.

### `OrganizationExportArtifact`

An export is an expiring ZIP stored through the tenant object-storage contract. It
contains:

- `manifest.json`;
- one NDJSON file per included relational table;
- organization membership/principal records for full-organization exports;
- an object inventory with checksums and verification state;
- optional controlled object bytes.

The manifest records scope, table counts, object metadata, generation time and a
canonical digest. API keys, request headers, cookies and provider secrets are not
part of the export model.

### `DataSubjectRequest`

Supported reviewed scopes in WP-10:

- project export or deletion;
- learner-identity export or deletion.

State machine:

```text
requested -> approved -> running -> verifying -> completed
     |                         |          |
     +-> denied               +-> blocked
     +-> cancelled            +-> failed -> retry
```

Creation and approval use separate idempotency keys. Project deletion requires the
approver to differ from the requester. The reviewer principal and final reason are
persisted.

### `HumanReviewCase` and `HumanReviewEvent`

Cases support open, assigned, decided, appealed and closed states. Events are
append-only. AI or system code may create a case and attach bounded evidence, but a
`decision` event is rejected unless `actor_type == human`. The API always derives
the decision actor from an authenticated principal.

## 3. Export flow

```text
authorized request
  -> idempotency lookup
  -> expiring artifact row
  -> tenant-aware background job
  -> relational snapshot
  -> object stat/checksum verification
  -> optional object inclusion
  -> canonical manifest digest
  -> checksum-verified object write
  -> completed artifact
  -> authorization recheck on download
```

`ORGANIZATION_EXPORT_MAX_BYTES` bounds the final package and included object bytes.
Download uses private streaming or a bounded presigned redirect according to the
existing storage configuration.

## 4. Verified deletion

### Project

1. Recheck human approval and active legal holds.
2. Delete each active project object through `StorageService`.
3. Confirm the backend reports every object absent.
4. Preserve minimal `StoredObject` tombstones with `status=deleted`.
5. Delete the project and database-cascaded content.
6. Confirm the project row count is zero.
7. Commit counts and verification evidence.

Audit events and model-usage ledger entries are protected compliance records and
are not erased by project deletion.

### Learner identity

The existing resumable long-term-memory deletion service removes source events,
derived state, preferences, plans, identity links and generated memory exports. The
WP-10 worker then verifies that the identity no longer exists and records the
underlying memory-deletion audit ID.

### Failure and retry

Object deletion is idempotent. If a worker fails after deleting some physical
objects but before committing relational changes, a retry can safely reissue
deletes and converge. Failed and legal-hold-blocked requests remain explicit and
may be retried only while their human approval remains valid.

## 5. Bypass prevention

In enterprise/authenticated mode, the legacy direct project delete endpoint returns
`reviewed_deletion_required`. In every mode, an active legal hold blocks that
endpoint. Local disabled-mode compatibility remains available for existing v0.8
tests and evaluation data.

## 6. Authorization

| Operation | Capability |
|---|---|
| Read policy/hold state | `retention.read` |
| Update policy or legal holds | `retention.manage` |
| Create/download organization exports | `retention.manage` |
| Create a data-subject request | `review_case.create` |
| Decide/retry destructive requests | `retention.manage` |
| Create a review case | `review_case.create` |
| Assign or decide a case | `review_case.review` |
| Appeal a decided case | `review_case.appeal` |

Every `/api/v1` route is registered in the centralized route-policy registry and
inherits request/trace correlation plus immutable audit behavior.

## 7. PostgreSQL controls

Migration `20260728_0016`:

- creates six tenant-owned lifecycle/review tables;
- enables and forces RLS for `ai_examiner_runtime`;
- revokes runtime delete on every compliance table;
- grants review events select/insert only;
- refuses downgrade while requests, export artifacts or review evidence exist.

## 8. Known boundary

WP-10 provides policy storage and reviewed deletion, not a silent scheduled purge.
Automatic enforcement sweeps must be introduced only with preview, backup and
recovery evidence. This prevents a configuration mistake from becoming immediate
irreversible loss.
