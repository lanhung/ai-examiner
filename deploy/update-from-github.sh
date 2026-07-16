#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
if [[ "${USE_HTTPS:-false}" == "true" ]]; then
  COMPOSE_FILES+=(-f docker-compose.https.yml)
fi

printf '\n[1/9] Backing up application data...\n'
./deploy/backup.sh

printf '\n[2/9] Fetching latest source while the current release stays online...\n'
git fetch --tags origin

git checkout "${DEPLOY_BRANCH:-main}"
git pull --ff-only origin "${DEPLOY_BRANCH:-main}"

printf '\n[3/9] Building images while the current release stays online...\n'
docker compose "${COMPOSE_FILES[@]}" build --pull

printf '\n[4/9] Stopping current containers...\n'
docker compose "${COMPOSE_FILES[@]}" down --remove-orphans

printf '\n[5/9] Applying database migrations...\n'
docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps ai-examiner alembic upgrade head

printf '\n[6/9] Starting services...\n'
docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans

printf '\n[7/9] Waiting for health check...\n'
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/health" >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/health"

printf '\n[8/9] Service status...\n'
docker compose "${COMPOSE_FILES[@]}" ps

printf '\n[9/9] Recent application logs...\n'
docker compose "${COMPOSE_FILES[@]}" logs --tail=50 ai-examiner
