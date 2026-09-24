# AI Examiner v0.9.4

Release date: 2026-09-04

## Purpose

v0.9.4 improves the workbench layout after the preparation column proved too
narrow for its workflow density. The release changes presentation only; no API,
database, authentication or runtime model contract changes are included.

## Changes

- The desktop preparation rail now uses a stable `420-460px` width.
- At narrower desktop widths the rail remains between `380-420px`.
- The workbench switches to a single column at `1080px`, before setup controls
  become compressed.
- Paired setup fields reserve at least `144px` for the secondary field.
- Text and voice start actions share available width evenly and wrap cleanly.
- Long model metadata may wrap without forcing horizontal overflow.

## Compatibility

- No database migration is required.
- Existing `.env` files remain compatible.
- Existing workbench element IDs and JavaScript event bindings are unchanged.
- `v0.9.3` is the immediate rollback version.

## Deployment

Use the existing deployment script after the commit reaches the deployment
branch:

```bash
cd /root/autodl-tmp/ai-examiner-mvp/ai-examiner-v0.9-staging
./deploy/autodl-stop.sh
./deploy/autodl-v09-enterprise-start.sh
```

After deployment, reload the browser without cache so the `v0.9.4` stylesheet
is fetched.
