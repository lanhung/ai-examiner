# AI Examiner v0.9.2

Release date: 2026-08-17

## Purpose

v0.9.2 reduces excessive whitespace between workbench modules without changing
enterprise APIs, data models, tenancy, authentication or examination behavior.

## Changes

- Reduces the main grid gap from 16px to 10px.
- Compacts panel padding and step spacing.
- Uses smaller empty-state minimum heights for evidence, text, voice and template
  surfaces while retaining larger scrollable areas when content is present.
- Reduces header and workflow-navigation height.
- Tightens tablet and mobile page padding without shrinking touch controls.

## Compatibility

- No migration is required from v0.9.1.
- Existing `.env`, PostgreSQL, Redis, S3 data and uploaded documents are reused.
- `v0.9.1` remains the rollback tag.

## Verification

- 352 automated tests passed.
- Ruff and frontend JavaScript syntax checks passed.
- Desktop page height fell by approximately 22% in the empty workbench state.
- Browser checks passed at 1280px and 390px with no horizontal overflow.
