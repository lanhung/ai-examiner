# v0.9 Resource Ownership and Capability Matrix

Status: Research draft
Purpose: authoritative inventory for tenant migration and route authorization

## 1. Ownership rules

Ownership types:

```text
global          reviewed deployment resource; never tenant-authored
organization    directly controlled by one organization
project         organization-owned through a project and direct organization column
learner         organization-owned learner data
operational     deployment operation with separately authorized access
```

All `project` and `learner` rows receive a direct `organization_id` for RLS even when
ownership can be inferred through another foreign key.

## 2. Current model inventory

| Current model | v0.9 ownership | Migration source | Required invariant |
|---|---|---|---|
| `Project` | organization | legacy organization | organization is non-null |
| `ScenarioTemplate` | global or organization | `owner_scope` | built-in is global; local is organization-owned |
| `ScenarioTemplateVersion` | template | template | same ownership as template |
| `TemplateValidationRun` | template | template version | same ownership as version |
| `ProjectTemplateBinding` | project | project | version is global or same organization |
| `Document` | project | project | storage key uses same organization/project |
| `Blueprint` | project | project | document belongs to same project and organization |
| `ExamSession` | project | project | blueprint and learner subject are authorized |
| `Turn` | project | session | same organization as session |
| `UsageEvent` | organization/project | project or job context | every billable call has organization |
| `GoldenDataset` | project | project | document belongs to same project |
| `BenchmarkRun` | project | project | dataset and document share organization |
| `ExpertRating` | project | dataset | rater principal is recorded separately |
| `EvidenceAsset` | project | project | document and object key share organization |
| `VisualAnalysis` | project | project | evidence asset is in same project |
| `PromptVersion` | global or organization | seeded/global versus local | organization prompt cannot override another tenant |
| `BackgroundJob` | organization/project | project or explicit system kind | actor and idempotency are mandatory |
| `JointAnalysis` | project | project | every document is in project |
| `VoiceSession` | project | project | exam session is same organization |
| `VoiceEvent` | project | voice session | same organization as voice session |
| `KnowledgeUnit` | project | blueprint | same organization as blueprint |
| `QuestionKnowledgeUnit` | project | knowledge unit | question belongs to same blueprint |
| `LearnerSubject` | learner/project | project | organization inherited from project |
| `LearnerIdentity` | learner | legacy identity link | organization is explicit; no implicit cross-org identity |
| `LearnerIdentityLink` | learner/project | subject and identity | both sides share organization |
| `Concept` | global or organization | reviewed canonical versus local | local concept is tenant-private |
| `KnowledgeUnitConceptMap` | learner/project | knowledge unit | concept is global or same organization |
| `LearnerMemoryEvent` | learner | identity/subject | all references share organization |
| `LearnerConceptState` | learner | identity | concept is global or same organization |
| `RetestPlan` | learner | identity | organization is non-null |
| `RetestItem` | learner | plan | concept is global or same organization |
| `LearnerPreference` | learner | identity | self/admin access differs |
| `MemoryExportArtifact` | learner | identity | object key is tenant-prefixed |
| `MemoryDeletionAudit` | learner | identity or retained tenant ID | minimal audit survives content deletion |
| `KnowledgeState` | project/learner | session | subject, unit and session share organization |
| `KnowledgeEvidenceEvent` | project/learner | session | turn, unit and subject share organization |
| `AdaptiveDecision` | project | session | same organization as session |

New enterprise models:

| New model | Ownership | Notes |
|---|---|---|
| `Organization` | organization root | lifecycle and status |
| `Principal` | deployment identity | keyed by issuer/subject; access only through membership |
| `OrganizationMembership` | organization | role and status |
| `ServiceAccount` | organization | non-interactive principal |
| `ServiceAccountToken` | organization | hash only |
| `OrganizationPolicy` | organization | security and feature policy |
| `OrganizationModelPolicy` | organization | provider/model/data classification |
| `UsageLedgerEntry` | organization/project | authoritative cost event |
| `AuditEvent` | organization | append-only |
| `RetentionPolicy` | organization | bounded by deployment minimums |
| `DataSubjectRequest` | organization/learner | export/delete workflow |
| `ReviewCase` | organization/project | human review and appeal |

## 3. Capability registry

### Organization administration

```text
organization.read
organization.update
organization.delete
member.read
member.manage
member.grant_owner
service_account.read
service_account.manage
policy.read
policy.manage
audit.read
usage.read
retention.read
retention.manage
```

### Examination work

```text
project.create
project.read
project.update
project.delete
document.create
document.read
document.delete
blueprint.create
blueprint.read
session.create
session.conduct
session.read
report.read
dataset.manage
benchmark.run
expert_rating.create
```

### Template and prompt work

```text
template.read
template.author
template.review
template.publish
template.bind
prompt.read
prompt.author
prompt.activate
```

### Learner and review work

```text
learner.read
learner.manage
learner_memory.read_self
learner_memory.manage_self
learner_memory.admin
retest.manage
review_case.create
review_case.review
review_case.appeal
```

### Operations

```text
job.read
job.manage
provider_health.read
system_metrics.read
system_backup.run
```

## 4. Role defaults

| Capability family | owner | admin | examiner | template author | reviewer | learner | auditor |
|---|---:|---:|---:|---:|---:|---:|---:|
| organization lifecycle | yes | limited | no | no | no | no | read |
| membership/service account | yes | yes | no | no | no | no | read |
| policy/quota/retention | yes | yes | no | no | read | no | read |
| projects/documents | yes | yes | yes | read | read | assigned | read |
| sessions/reports | yes | yes | yes | read | review | assigned | read |
| template authoring | yes | yes | read | yes | review | read | read |
| template publish | yes | yes | no | no | review-only | no | read |
| learner administration | yes | yes | assigned | no | assigned | self | read |
| audit/usage | yes | yes | own projects | no | review cases | self usage only | yes |
| destructive organization action | yes | no | no | no | no | no | no |

The table defines defaults. The capability registry remains authoritative.

WP-04 encodes the exact bundles in `enterprise_constants.py`. Only `owner` receives
`member.grant_owner`; ordinary `member.manage` cannot create, demote, suspend or
revoke owner memberships.

## 5. Existing route authorization map

### Public and system routes

| Current route | v0.9 rule |
|---|---|
| `GET /` | public application shell; no tenant data |
| `GET /health` | public liveness, minimal detail |
| `GET /ready` | operator-protected detail |
| `GET /api/providers` | authenticated; filtered by organization model policy |
| `GET /api/provider-health` | `provider_health.read`; no secret values |

### Templates and prompts

| Current route group | Capability | Resource rule |
|---|---|---|
| template list/get/export/diff/preview | `template.read` | global or same organization |
| template create/import/clone/update | `template.author` | organization draft only |
| template validate/compile | `template.author` | organization draft or review assignment |
| template lifecycle status | `template.review` or `template.publish` | transition-specific |
| project template binding get | `project.read` + `template.read` | project tenant |
| project template binding put/delete | `template.bind` + `project.update` | version global/same tenant |
| prompt list | `prompt.read` | global or same tenant |
| prompt create | `prompt.author` | organization draft |
| prompt activate | `prompt.activate` | same organization |

### Projects and material

| Current route group | Capability |
|---|---|
| project create | `project.create` |
| project list/get | `project.read` |
| project delete | `project.delete` |
| document upload | `document.create` |
| document list/evidence/file/highlight | `document.read` |
| blueprint creation | `blueprint.create` |
| visual/joint analysis create | `document.read` + `blueprint.create` |
| visual/joint analysis read | `blueprint.read` |

Evidence file routes resolve the asset inside organization context before opening any
storage backend.

### Dataset and evaluation

| Current route group | Capability |
|---|---|
| Golden Dataset create/status/export | `dataset.manage` |
| benchmark create/read | `benchmark.run` / `dataset.manage` |
| expert rating create | `expert_rating.create` |
| agreement read | `dataset.manage` or `review_case.review` |
| policy/longitudinal evaluation | `benchmark.run` |

### Sessions and reports

| Current route group | Capability |
|---|---|
| session create | `session.create` |
| session start/answer | `session.conduct` |
| session read/template/knowledge/decisions | `session.read` |
| report read | `report.read` |
| knowledge rebuild | `learner.manage` or `session.conduct` |
| voice config | authenticated and policy-filtered |
| voice create/SDP/events/complete | `session.conduct` |
| voice read | `session.read` |

Session assignment may further restrict a learner to their assigned session even when
the role contains a self-service capability.

### Learner memory

| Current route group | Capability |
|---|---|
| identity create/link/unlink | `learner.manage` |
| identity read | `learner.read` or self |
| concept create/mapping review | `learner.manage` |
| memory import/rebuild | `learner_memory.admin` |
| concept state/growth/retest plan | `learner.read` / `retest.manage` |
| preference create/read/update | self or `learner_memory.admin` |
| memory correction/export/delete | self or `learner_memory.admin` |
| deletion retry/audit | `learner_memory.admin` |
| memory center/history | self, assigned examiner or administrator |

Self access is resolved from the principal-to-learner binding, never from an identity
ID supplied alone.

### Jobs, costs and metrics

| Current route group | Capability |
|---|---|
| job read | `job.read` in same tenant |
| job retry/cancel | `job.manage` |
| cost view | `usage.read` |
| application metrics | `system_metrics.read`; public scrape uses network auth |

## 6. Authorization implementation rule

Every route registry entry contains:

```python
RoutePolicy(
    authentication="required",
    capability="document.read",
    resource_resolver="evidence_asset_in_organization",
    audit="read_sensitive",
)
```

CI compares the FastAPI route inventory with the policy registry. Any unclassified
non-public route fails the build.

## 7. Migration verification queries

Research prototypes must prove:

```text
every required tenant row has organization_id
every project child organization equals project organization
every learner link shares organization
every local template/prompt/concept has organization
every billable usage event has organization
every job has organization or allowlisted system kind
every object locator starts with its tenant prefix
```

Conflicting or orphaned records stop migration and appear in a redacted remediation
report.
