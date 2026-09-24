# ADR-007: Assignments as the learner entry point

Status: Proposed for v0.10
Date: 2026-09-24

## Context

Until v0.9 every exam session is created from the workbench by someone who can
see projects, uploaded material, blueprints and model profiles. That works for
self-practice and for examiners running sessions themselves, but not for a class:
a teacher wants to prepare once and let many learners start on their own, and
learners must not see the preparation artifacts, the scoring internals or other
learners' attempts.

The existing session API cannot be handed to learners as-is:

- it requires `session.create` / `session.conduct`, which also grant access to
  every session in the organization;
- its responses include per-turn analysis, evaluation and policy decisions, and
  the report includes source excerpts and evidence;
- session settings (hints, corrections, profile) are chosen per request by the
  caller.

## Decision

### 1. A separate `Assignment` object publishes a blueprint

An `Assignment` references one project and blueprint and freezes everything a
learner session needs: mode (`practice` or `exam`), session settings merged into
mode defaults, the resolved model profile, open/close times, attempt limit and
whether the learner key is required. Once published, mode, blueprint and settings
are immutable; only presentation, window, limits, status and result release can
change.

### 2. Six-character join codes, unique per organization

Codes use a 32-character alphabet without `I`, `O`, `0` and `1`. 32^6 ≈ 1.07
billion codes per organization keeps random guessing impractical at the request
rates the API sees, while still being easy to read aloud and type on a phone.
Uniqueness is enforced by a database constraint on `(organization_id,
join_code)`.

### 3. Each attempt owns exactly one exam session

`AssignmentAttempt.session_id` is unique. The attempt stores the learner account
(`principal_id`) when there is one, an optional normalized learner key, a display
name and a SHA-256 hash of a random 256-bit attempt token. The token is returned
once at creation and compared with `hmac.compare_digest`.

A learner route accepts a request only if the caller's account owns the attempt
or the `X-AI-Examiner-Attempt-Token` header matches. Otherwise it answers `404`,
so attempt IDs do not reveal whether an attempt exists.

### 4. Anonymous learners are allowed, bound to one organization

Learners do not need an OIDC account. The join code gets them to the start of an
attempt and the attempt token proves ownership after that. Anonymous requests run
in the tenant context of `X-AI-Examiner-Organization` (default: the legacy
organization), so PostgreSQL RLS still scopes every read. Authenticated learners
need `assignment.attempt` in the selected organization.

### 5. Exam mode locks the conversation policy in the trusted path

`_create_exam_session(..., exam_lock=True)` passes the effective conversation
policy through `lock_conversation_policy()`, which removes `GIVE_HINT` and
`CORRECT` and disables hints, corrections and answer disclosure regardless of the
scenario template. The existing policy controller already downgrades disallowed
actions, so no orchestrator change is needed. Teachers cannot request hints for
an exam; the API rejects it rather than silently changing the setting.

### 6. Learner views are allow-lists, not redactions

`learner_turn_view`, `learner_attempt_view`, `public_assignment_view` and
`learner_report_view` build new dictionaries from named fields. Anything added to
the internal report or turn payloads later stays invisible to learners unless
someone adds it explicitly. Exam results stay at "submitted" until
`results_released` is set.

### 7. The workbench session endpoints share one implementation

The bodies of `create_session`, `start_session`, `submit_answer` and `get_report`
moved into `_create_exam_session`, `_start_exam_session`, `_submit_exam_answer`
and `_build_session_report`. The workbench endpoints call them with the defaults
and keep their responses unchanged; assignment endpoints call them and then
reduce the output.

### 8. Tenant ownership and RLS follow the v0.9 pattern

Migration `20260924_0018` creates both tables from model metadata, grants the
runtime role `SELECT, INSERT, UPDATE` (no `DELETE`), and enables and forces the
`tenant_isolation` policy. `deploy/verify-v09-rls.py` requires both tables.

## Consequences

- Teachers get a stable link per assignment; learners see three screens.
- Attempt-level ownership replaces organization-wide session capabilities for
  learners.
- `max_attempts` is only meaningful for learners with an account or a learner
  key; the product documentation says so.
- Join lookups for anonymous learners in a non-legacy organization need the
  organization ID in the link (`/x/{code}?org=...`). A global code index across
  organizations was rejected because it would need a table outside RLS.
- There is no teacher UI in this increment; the API is complete.

## Alternatives considered

- **Reuse session capabilities for learners.** Rejected: `session.conduct`
  covers every session in the organization.
- **Signed stateless tokens (JWT) for attempts.** Rejected: revocation and
  rotation would need extra state anyway, and a hashed random token in the
  attempt row is simpler to audit.
- **Redacting the full report for learners.** Rejected in favour of allow-lists
  (decision 6).
