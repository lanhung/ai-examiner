#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
if [[ "${USE_HTTPS:-false}" == "true" ]]; then
  COMPOSE_FILES+=(-f docker-compose.https.yml)
fi

printf '\n[1/8] Backing up application data...\n'
./deploy/backup.sh

printf '\n[2/8] Stopping current containers...\n'
docker compose "${COMPOSE_FILES[@]}" down --remove-orphans

printf '\n[3/8] Fetching latest source...\n'
git fetch --tags origin

git checkout "${DEPLOY_BRANCH:-main}"
git pull --ff-only origin "${DEPLOY_BRANCH:-main}"

printf '\n[4/8] Building images without stale application layers...\n'
docker compose "${COMPOSE_FILES[@]}" build --pull

printf '\n[5/8] Starting services...\n'
docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans

printf '\n[6/8] Waiting for health check...\n'
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/health" >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/health"

printf '\n[7/8] Service status...\n'
docker compose "${COMPOSE_FILES[@]}" ps

printf '\n[8/8] Recent application logs...\n'
docker compose "${COMPOSE_FILES[@]}" logs --tail=50 ai-examiner
