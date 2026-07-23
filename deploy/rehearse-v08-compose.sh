#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for the v0.8 Compose rehearsal." >&2
  exit 2
fi

PROJECT_NAME="${REHEARSAL_PROJECT_NAME:-ai-examiner-v08-rehearsal}"
case "$PROJECT_NAME" in
  ai-examiner-v08-rehearsal*) ;;
  *)
    echo "Refusing unsafe rehearsal project name: $PROJECT_NAME" >&2
    exit 2
    ;;
esac

WORK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ai-examiner-v08-rehearsal.XXXXXX")"
DATA_DIR="$WORK_ROOT/data"
ENV_FILE="$WORK_ROOT/rehearsal.env"
PORT="${REHEARSAL_PORT:-18080}"
mkdir -p "$DATA_DIR"

cleanup() {
  APP_ENV_FILE="$ENV_FILE" \
  HOST_DATA_DIR="$DATA_DIR" \
  APP_PORT="$PORT" \
    docker compose \
      -p "$PROJECT_NAME" \
      -f docker-compose.yml \
      -f docker-compose.prod.yml \
      down --remove-orphans -v >/dev/null 2>&1 || true
  case "$WORK_ROOT" in
    "${TMPDIR:-/tmp}"/ai-examiner-v08-rehearsal.*)
      rm -rf -- "$WORK_ROOT"
      ;;
    *)
      echo "Refusing to remove unexpected rehearsal path: $WORK_ROOT" >&2
      ;;
  esac
}
trap cleanup EXIT

grep -vE '^(MODEL_PROVIDER|DATABASE_URL|UPLOAD_DIR|EVIDENCE_DIR|EXPORT_DIR|BACKUP_DIR)=' \
  .env.example >"$ENV_FILE"
cat >>"$ENV_FILE" <<'EOF'
MODEL_PROVIDER=mock
DATABASE_URL=sqlite:////app/data/rehearsal.db
UPLOAD_DIR=/app/data/uploads
EVIDENCE_DIR=/app/data/evidence
EXPORT_DIR=/app/data/exports
BACKUP_DIR=/app/data/backups
GOLDEN_DEFAULT_PROFILES=mock:heuristic-v2
BENCHMARK_DEFAULT_PROFILES=mock:heuristic-v2
VISUAL_DEFAULT_PROFILE=mock:heuristic-v2
EOF
chmod 600 "$ENV_FILE"

compose() {
  APP_ENV_FILE="$ENV_FILE" \
  HOST_DATA_DIR="$DATA_DIR" \
  APP_PORT="$PORT" \
    docker compose \
      -p "$PROJECT_NAME" \
      -f docker-compose.yml \
      -f docker-compose.prod.yml \
      "$@"
}

echo "[1/8] Validate Compose configuration"
compose config --quiet

echo "[2/8] Build images"
compose build

echo "[3/8] Apply migrations to isolated SQLite data"
compose run --rm --no-deps ai-examiner alembic upgrade head

echo "[4/8] Start isolated services"
compose up -d --remove-orphans

echo "[5/8] Wait for API health"
healthy=false
for _ in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ "$healthy" != true ]]; then
  compose logs --tail=200
  exit 1
fi

echo "[6/8] Verify persisted built-in template health"
curl -fsS "http://127.0.0.1:${PORT}/api/templates/health" \
  | grep -q '"status":"ok"'

echo "[7/8] Run deterministic template gates inside the image"
compose run --rm --no-deps ai-examiner \
  ai-examiner-evaluate-templates \
  --output /app/data/template-evaluation-report.json \
  --performance-samples 30

echo "[8/8] Create and inspect an isolated backup"
compose run --rm --no-deps ai-examiner \
  ai-examiner-backup \
  --output /app/data/backups/rehearsal.tar.gz
test -s "$DATA_DIR/backups/rehearsal.tar.gz"
tar -tzf "$DATA_DIR/backups/rehearsal.tar.gz" >"$WORK_ROOT/backup-contents.txt"
grep -q 'rehearsal.db' "$WORK_ROOT/backup-contents.txt"

cat <<EOF
v0.8 Docker Compose rehearsal passed.
Project: $PROJECT_NAME
Port: $PORT
Temporary data: $DATA_DIR
The cleanup trap will now remove only this rehearsal project and directory.
EOF
