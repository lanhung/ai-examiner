# AI Examiner v0.9.1

Release date: 2026-08-11

## Purpose

v0.9.1 is a presentation and usability refinement for the accepted v0.9
enterprise platform. It does not change backend APIs, database schemas, tenant
boundaries, model routing or examination behavior.

## Changes

- Makes project preparation and live examination the first workbench tasks.
- Moves scenario-template administration below the primary examination workflow.
- Adds compact sticky navigation for the main operational surfaces.
- Improves typography, spacing, focus states, buttons, tables and status badges.
- Refines the enterprise console sidebar, metrics, forms and responsive behavior.
- Keeps card radii at 8px or below and removes marketing-scale workbench headings.

## Compatibility

- No migration is required from v0.9.0.
- Existing `.env`, PostgreSQL, Redis, object storage and uploaded data are reused.
- `v0.9.0` remains the exact rollback tag.

## Verification

- 352 automated tests passed.
- Ruff and both frontend JavaScript syntax checks passed.
- The main workbench and enterprise console were visually checked at 1280px and
  390px widths with no horizontal overflow or browser console errors.
