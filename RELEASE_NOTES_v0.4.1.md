# AI Examiner v0.4.1

## Release purpose

v0.4.1 formalizes the currently deployed v0.4 series as a reproducible baseline before the v0.5 Adaptive Cognitive Engine work begins.

## Changes since the original v0.4.0 source publication

- Persist downloaded Ollama models across AutoDL/Vultr container rebuilds and restarts.
- Select the model used for blueprint generation independently.
- Select the model used for text examination independently.
- Add a maintained changelog and a stable annotated release tag.

## Compatibility

- No database schema changes.
- No API removals.
- Existing `.env`, `data/`, uploads, evidence assets, reports and Ollama model data remain compatible.
- Existing Docker Compose deployment commands remain unchanged.

## Verification

Before tagging, run:

```bash
python -m pytest
python -m ruff check src tests
node --check src/ai_examiner/static/app.js
```

## Upgrade

```bash
cd /root/autodl-tmp/ai-examiner-mvp/ai-examiner-mvp-v0.4.0
./deploy/backup.sh
git pull --ff-only origin main
docker compose down --remove-orphans
docker compose up -d --build --remove-orphans
```

Do not use `docker compose down -v`; it can delete persistent volumes.
