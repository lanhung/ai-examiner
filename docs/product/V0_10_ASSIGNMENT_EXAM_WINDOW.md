# v0.10 Assignment Exam Window

Date: 2026-09-24

Branch: `feature/v0.10-assignment-exam-window`

Decision record: [ADR-007](../decisions/ADR-007-ASSIGNMENT-EXAM-WINDOW.md)

## Goal

A teacher publishes an **assignment** from an existing blueprint. Learners open
`/x/{code}` (or `/exam` and type the code), enter a six-character join code and
start answering immediately. The learner page has exactly three screens: join,
conversation, result. It never shows workbench vocabulary (project, material,
blueprint, model).

The application version is unchanged (still `0.9.1`) and the enterprise console
is untouched.

## Concepts

| Object | Meaning |
|---|---|
| `Assignment` | A published exam window over one blueprint: title, mode, join code, frozen session settings, open/close time, attempt limit, result release flag. |
| `AssignmentAttempt` | One learner attempt. Owns exactly one `ExamSession` (`session_id` is unique) and stores only a SHA-256 hash of the attempt token. |

Both tables are tenant-owned (`TenantOwnedMixin`) and protected by the same
PostgreSQL row-level security policy as the other v0.9 tenant tables (migration
`20260924_0018`, registered in `deploy/verify-v09-rls.py`).

### Modes

| Mode | Hints / corrections | Results shown to the learner |
|---|---|---|
| `practice` | Allowed by default (teacher may turn off). | Immediately after submission. |
| `exam` | Always off. The conversation policy is locked: `GIVE_HINT` and `CORRECT` are removed and hints, corrections and answer disclosure are disabled. Requesting hints for an exam is rejected with `422`. | Only "submitted" until the teacher sets `results_released=true`. |

### Frozen settings

At publish time the teacher's `session_settings` are merged into the mode
defaults and stored on the assignment. The default model profile is resolved and
frozen too. Mode, blueprint and `session_settings` cannot be changed later
(`PATCH` rejects them with `422`); publish a new assignment instead.

| Setting | practice default | exam default |
|---|---|---|
| `question_limit` | 5 | 5 |
| `max_followups_per_question` | 2 | 1 |
| `question_strategy` | fixed | fixed |
| `session_mode` | defense | defense |
| `allow_hints` / `allow_corrections` | true / true | false / false (locked) |

### Join codes

Six characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. `I`, `O`, `0` and `1`
are excluded because learners confuse them. Input is case-insensitive and
spaces/dashes are ignored. Codes are unique within an organization
(`uq_assignment_organization_join_code`).

### Exam window

`window_state` is one of `open`, `scheduled` (before `opens_at`), `ended`
(after `closes_at`) or `closed` (teacher set `status=closed`). Creating an
attempt, starting it and submitting answers all require `open`, so closing an
assignment also stops in-progress attempts.

`max_attempts` is counted per learner account, or per normalized learner key for
anonymous learners. Anonymous learners without a learner key cannot be counted;
set `require_learner_key=true` when the limit matters.

## Capabilities

| Capability | owner / admin | examiner | reviewer | auditor | learner | template_author |
|---|---|---|---|---|---|---|
| `assignment.manage` | yes | yes | – | – | – | – |
| `assignment.read` | yes | yes | yes | yes | – | – |
| `assignment.attempt` | yes | yes | – | – | yes | – |

## API

Teacher routes use the workbench authorization (`X-AI-Examiner-Organization`,
OIDC in enterprise mode, legacy organization in local disabled-auth mode).

| Method | Path | Capability |
|---|---|---|
| POST | `/api/assignments` | `assignment.manage` |
| GET | `/api/assignments?project_id=` | `assignment.read` |
| GET | `/api/assignments/{id}` | `assignment.read` |
| PATCH | `/api/assignments/{id}` | `assignment.manage` |
| GET | `/api/assignments/{id}/dashboard` | `assignment.read` |

Learner routes accept either an authenticated account holding
`assignment.attempt` or an anonymous caller. Anonymous callers are bound to the
organization in `X-AI-Examiner-Organization` (default: legacy organization); the
page forwards `?org=` from the URL.

| Method | Path | Ownership |
|---|---|---|
| GET | `/api/join/{code}` | join code |
| POST | `/api/join/{code}/attempts` | join code; returns `attempt_token` once |
| POST | `/api/attempts/{id}/start` | own account or `X-AI-Examiner-Attempt-Token` |
| POST | `/api/attempts/{id}/answers` | own account or token |
| GET | `/api/attempts/{id}` | own account or token |
| GET | `/api/attempts/{id}/report` | own account or token |

An attempt that does not belong to the caller returns `404 attempt_not_found`,
indistinguishable from a missing attempt.

Pages: `GET /exam`, `GET /x/{code}`.

### Learner-visible data

Learner responses contain only: title, mode, introduction, window state and
times, attempt limits, the conversation text (`id`, `role`, `content`,
`created_at`) and, when allowed, a reduced result: overall score, maximum score,
questions answered, strengths, improvement statements, recommended actions and
the disclaimer.

They never contain analysis, per-answer evaluation, policy decisions, project,
blueprint or session identifiers, session settings, model profile, expected
points, source excerpts, evidence, rubrics or knowledge maps. The test suite
enforces this key-by-key and by searching for blueprint secrets.

## Workbench compatibility

`create_session`, `start_session`, `submit_answer` and `get_report` now delegate
to `_create_exam_session`, `_start_exam_session`, `_submit_exam_answer` and
`_build_session_report`. `_create_exam_session(..., exam_lock=False)` is the
default, so the existing `/api/sessions/*` endpoints return the same payloads as
before; only assignment attempts pass `exam_lock=True`.

## Test coverage

`tests/test_assignments_v010.py`:

- **Unit:** join-code alphabet and normalization, per-mode frozen defaults, exam
  assistance rejection, `lock_conversation_policy`, window state, attempt limits,
  SHA-256 token storage with `hmac.compare_digest`, learner report reduction,
  capability bundles.
- **Integration:** full practice flow, exam lock and result release, validation
  of frozen fields and windows, unique join codes, learner keys, closing and
  scheduling, unchanged `/api/sessions` contract, project deletion cascade, page
  routes.
- **Permissions:** role matrix on every route, account-bound attempts,
  per-account limits, cross-tenant `404`s, token/organization mismatch, OIDC
  mode (teacher routes private, anonymous token attempts allowed).
- **Leakage:** forbidden keys and blueprint secrets absent from every learner
  response, token returned exactly once and never stored in clear, exam results
  hidden before release, no workbench vocabulary on the learner page.

## Known limits

- The teacher side is API-only in this increment; there is no workbench UI yet.
- Anonymous join in a non-legacy organization needs `?org=<organization id>` in
  the link.
- Attempt numbering is computed at insert time; two simultaneous joins by the
  same learner can both succeed at the limit boundary.
