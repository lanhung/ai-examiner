#!/usr/bin/env bash
# Shared Compose file selection for update, rollback and backup scripts.
#   USE_PILOT=true  -> classroom pilot (Caddy + teacher password, see Caddyfile.pilot)
#   USE_HTTPS=true  -> plain HTTPS profile (docker-compose.https.yml)
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
if [[ "${USE_PILOT:-false}" == "true" ]]; then
  COMPOSE_FILES+=(-f docker-compose.pilot.yml)
elif [[ "${USE_HTTPS:-false}" == "true" ]]; then
  COMPOSE_FILES+=(-f docker-compose.https.yml)
fi
