# AI Examiner UI Design System

Status: Historical reference
Applies to: Workbench (`/`) and enterprise console (`/enterprise`)

The current v0.9 build restores the accepted v0.9.0 interface and does not apply the compact
layout experiments documented below. This file is retained so the v0.9.1 to
v0.9.5 design decisions remain auditable; it is not the active rendering
contract for the current classic interface revision.

## Product Character

AI Examiner is an operational assessment workspace. The interface should feel precise, calm, compact, and trustworthy. It should prioritize repeated work, evidence inspection, comparison, and clear state transitions rather than promotional presentation.

## Layout Principles

1. Keep the current task and its next action visible without excessive scrolling.
2. Group controls by workflow stage; do not show decorative containers around every subsection.
3. Avoid stacking large empty modules. Empty regions should collapse to concise placeholders.
4. Use full-width bands only for genuinely cross-workspace content. Repeated records may use bordered rows or compact cards.
5. At desktop widths, the preparation rail and active work surface should remain visible together.
6. On mobile, use a single column and horizontal navigation where appropriate; never compress two-column forms until labels or values collide.

## Spacing

Use a 4px base scale:

| Token | Value | Typical use |
|---|---:|---|
| `--space-1` | 4px | icon/label separation |
| `--space-2` | 8px | dense row and control gap |
| `--space-3` | 12px | panel gap and compact padding |
| `--space-4` | 16px | standard panel padding |
| `--space-6` | 24px | major page separation |
| `--space-8` | 32px | exceptional section separation |

Routine module gaps should be `8-12px`. Standard panel padding should be `12-16px`. Avoid fixed minimum heights unless interaction stability requires them.

## Typography

- Page title: `22-26px`, used once per page.
- Panel title: `15-18px`.
- Body: `13-14px`.
- Metadata: `11-12px`.
- Letter spacing: `0`.
- Chinese supporting copy should normally use `1.45-1.55` line height.
- Do not scale font size with viewport width.

## Surfaces

- Use a neutral page background and white primary surfaces.
- Border radius is at most `8px` unless an existing semantic control requires otherwise.
- Shadows should be subtle and reserved for elevation, not every nested region.
- Do not put cards inside cards. Use dividers, rows, tabs, or unframed groups inside a surface.
- Empty states should use a compact dashed or tinted region and one clear next action when available.

## Controls

- Primary buttons are reserved for the current workflow action.
- Secondary actions use neutral borders or quiet backgrounds.
- Icon buttons require accessible labels and tooltips when the symbol is unfamiliar.
- Inputs and buttons should normally be `36-40px` high on desktop and at least `40px` on touch-focused layouts.
- Status badges should not look like primary buttons.

## Workbench Density Targets

- Header: about `64-72px` on desktop.
- Sticky navigation: about `40-44px`.
- Main grid gap: `8-12px`.
- Preparation rail: `420-460px` on wide desktop and never below `380px` in a
  two-column layout.
- Switch the workbench to one column before the preparation rail would fall
  below `380px`; do not preserve two columns by squeezing form controls.
- Paired preparation controls should reserve at least `144px` for their compact
  secondary field and collapse to one column on mobile.
- Required setup should remain a short, numbered primary flow. Evaluation-only
  tooling belongs in a collapsed advanced disclosure until requested.
- Text and voice are alternate session modes and should share one active content
  region instead of occupying two full-height idle panels.
- At narrow widths, related two-option controls may remain in two columns down
  to `420px`; use one column only when labels or values would collide.
- Evidence empty state: no more than `120px` tall.
- Conversation empty state: no more than `180px` tall before a session begins.
- Voice idle area: no more than `240px` tall before connection.
- Status rows: collapse when empty; do not reserve more than one text line.

## Enterprise Density Targets

- Top bar: about `60-64px`.
- Sidebar: `208-228px` desktop width.
- Page padding: `16-28px` depending on viewport.
- Metrics: `68-78px` minimum height.
- Table rows: approximately `40-46px` unless content wraps.
- Form and surface gaps: `10-14px`.

## Responsive Checks

Validate representative widths near:

- `1440px`: wide desktop
- `1024px`: compact desktop/tablet landscape
- `768px`: tablet
- `390px`: mobile

At every width verify no text overlap, clipped controls, accidental horizontal page scrolling, sticky-header obstruction, or layout shifts caused by dynamic status content.

## Change Acceptance

A visual change is complete only when:

1. Existing element IDs and behavior remain intact.
2. Focus indicators and readable contrast remain present.
3. Long labels and realistic data have been checked.
4. Empty, loading, populated, error, and disabled states remain coherent.
5. UI contract tests pass.
6. The running page has been checked at desktop and mobile widths when browser control is available.
