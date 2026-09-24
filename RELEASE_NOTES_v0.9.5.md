# AI Examiner v0.9.5

Release date: 2026-09-04

## Purpose

v0.9.5 improves the information architecture of the workbench, especially in
the narrow in-app browser layout. It reduces page length and visual competition
without changing examination APIs, persisted data or provider behavior.

## Changes

- Required preparation is now a four-step workflow.
- Golden Dataset generation remains available in a collapsed advanced section.
- Text and voice examination use an accessible segmented mode control.
- Only the selected examination panel occupies layout space.
- Starting a text or voice session automatically selects the correct panel.
- Navigation links select and reveal the requested examination mode.
- Provider health uses ready, warning and error tones instead of one green badge.
- Authentication-required state is presented in concise Chinese.
- Narrow layouts use two-column voice, memory and preference controls until the
  viewport reaches `420px`.

## Compatibility

- No database migration is required.
- Existing `.env` files remain compatible.
- Existing workbench DOM IDs and API routes remain unchanged.
- `v0.9.4` is the immediate rollback version.
