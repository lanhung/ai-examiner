# AI Examiner v0.9.3

Release date: 2026-09-04

## Purpose

v0.9.3 makes the workbench and enterprise console substantially denser and
more consistent without changing any business API, database schema or identity
contract.

## Changes

- Added `docs/design/UI_DESIGN_SYSTEM.md` as the versioned visual contract.
- Reduced workbench header, navigation, grid, panel and empty-state footprint.
- Collapsed empty status rows instead of reserving blank vertical space.
- Reduced idle evidence, conversation and voice surface heights.
- Compacted memory, template, evaluation and report layouts.
- Reduced enterprise top bar, sidebar, content padding, metrics, table rows,
  records and empty states.
- Preserved 40px mobile control targets and responsive single-column behavior.

## Compatibility

- No database migration.
- No API change.
- Existing `.env`, PostgreSQL, Redis, S3/MinIO and OIDC configuration remains
  compatible.
- Roll back to `v0.9.2` if the denser layout is not suitable for a deployment.
