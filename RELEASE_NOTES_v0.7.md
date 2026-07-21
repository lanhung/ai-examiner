# AI Examiner v0.7.0 Release Candidate 1

v0.7 adds optional, user-controlled long-term learner intelligence without changing
the existing document, assessment or realtime voice paths when memory is disabled.

## Added

- HMAC-derived opaque learner identities and explicit project links.
- Reviewed canonical concept mappings and an idempotent evidence ledger.
- Replayable observed mastery, time-adjusted retention and growth series.
- Recommendation-only retest plans with accept, dismiss, cooldown, start and linked
  independent outcomes.
- Registry-limited explicit and user-confirmed preferences excluded from scoring.
- A responsive memory center that labels observations and predictions separately.
- Append-only corrections, short-lived JSON export and scoped asynchronous deletion.
- Deterministic offline longitudinal evaluation and PostgreSQL CI readiness.

## Safety posture

- Long-term memory is opt-in and can be disabled or deleted from the same UI.
- Automatic retest injection remains disabled; every retest is started by the user.
- Inferred preferences remain proposals until explicitly confirmed.
- Personality, emotion, medical, political, secret and unrestricted-summary memory
  categories are rejected.
- The 300-pair multilingual concept-mapping activation gate remains held; only
  explicitly accepted exact/narrower mappings affect longitudinal state.

## Migration

Alembic head is `20260721_0005`. Rehearse backup, upgrade and rollback using
`docs/deployment/V0_6_TO_V0_7_UPGRADE.md` before replacing a running evaluation
deployment.

## Known limits

- Memory APIs remain operator-bound until authentication and tenant authorization.
- Offline fixtures prove determinism and regression safety, not population validity.
- SQLite remains the supported single-server default; PostgreSQL is CI-ready but
  live data migration is a separate operation.
