#!/usr/bin/env bash
set -euo pipefail
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose ps
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/health
