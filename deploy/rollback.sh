#!/usr/bin/env bash
# Roll back to an earlier release.
#
#   ./deploy/rollback.sh v0.9.1 data/backups/ai-examiner-<stamp>.tar.gz
#
# Database migrations only move forward, so returning to older code also
# restores the backup that deploy/update-from-github.sh took before updating.
# Use the same USE_PILOT / USE_HTTPS values as for the update.
set -euo pipefail
if [[ "$#" -lt 1 || "$#" -gt 2 ]]; then
  echo "Usage: $0 GIT_TAG_OR_COMMIT [BACKUP_TARBALL]"
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/deploy/compose-files.sh"
DATA_DIR="${HOST_DATA_DIR:-$ROOT/data}"
REF="$1"
BACKUP="${2:-}"
if [[ -n "$BACKUP" && ! -f "$BACKUP" ]]; then
  echo "Backup not found: $BACKUP"
  exit 2
fi

git fetch --tags origin
git checkout "$REF"
docker compose "${COMPOSE_FILES[@]}" build
docker compose "${COMPOSE_FILES[@]}" down --remove-orphans

if [[ -n "$BACKUP" ]]; then
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  ASIDE="$ROOT/data-before-rollback-$STAMP"
  mkdir -p "$ASIDE"
  find "$DATA_DIR" -mindepth 1 -maxdepth 1 ! -name backups -exec mv {} "$ASIDE"/ \;
  tar -xzf "$BACKUP" -C "$DATA_DIR"
  echo "Restored $BACKUP (previous data kept in $ASIDE)"
else
  echo "WARNING: no backup given. If the newer release added a migration, the"
  echo "older release will not start until its matching backup is restored."
fi

docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/health" >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/health"
docker compose "${COMPOSE_FILES[@]}" ps
