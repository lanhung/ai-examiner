# v0.8 Increment I Template Studio Results

## Scope

Increment I implements WP-11 on `develop/v0.8.0`. It is a development
increment, not a release candidate.

## Browser workflow

The browser application was exercised against the real local FastAPI service and
SQLite persistence:

1. load seven reviewed built-ins and a local draft;
2. filter by category and high risk;
3. inspect immutable built-in metadata and compiled fingerprint;
4. preview effective settings;
5. select a published template for the next blueprint/session;
6. clone a built-in to a forced local draft;
7. edit and persist a structured assistance policy;
8. reload the draft and verify the persisted value.

The saved correction timing was `after_followups`, one of the strict contract
values. The success message remained visible after catalog and detail refresh.

## Responsive checks

At a 390 by 844 viewport:

- document width stayed within the viewport;
- the template catalog and editor stacked vertically;
- no template action button extended beyond the viewport;
- long labels wrapped without overlapping controls.

The temporary viewport override was reset after verification.

## Automated coverage

The increment adds regression tests that require:

- the v0.8 template studio and selector to ship with the root page;
- all correction timing values to match the backend contract;
- safe import, preview and semantic-diff routes to remain wired;
- selected templates to be included in blueprint, text-session and voice-session
  request construction.

Final local gates:

```text
WP-11 targeted pytest       16 passed
Full pytest                 118 passed
Full Ruff                   passed
JavaScript syntax           passed
Alembic head                20260723_0007
Alembic metadata drift      none
Wheel build                 passed
Tracked-source secret scan  no key patterns found
```

## Held gates

WP-12 still owns:

- scenario relevance evaluation;
- cross-provider real-model samples;
- migration and rollback rehearsal;
- Docker Compose and backup/restore rehearsal;
- final release notes, Vultr guide and release-candidate decision.

No v0.8 release tag is authorized by this increment.
