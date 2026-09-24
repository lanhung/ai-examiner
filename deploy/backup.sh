#!/usr/bin/env bash
# Consistent backup of the application data directory.
# The SQLite database is copied with SQLite's online backup API so a backup
# taken while students are answering is never half-written.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${HOST_DATA_DIR:-$ROOT/data}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$DATA_DIR/backups"
mkdir -p "$BACKUP_DIR"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

for database in "$DATA_DIR"/*.db; do
  [[ -e "$database" ]] || continue
  python3 - "$database" "$STAGING/$(basename "$database")" <<'PY'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1], timeout=60)
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close()
source.close()
PY
done

ARCHIVE="$BACKUP_DIR/ai-examiner-$STAMP.tar"
tar -cf "$ARCHIVE" --exclude='./backups' --exclude='*.db' --exclude='*.db-wal' \
  --exclude='*.db-shm' -C "$DATA_DIR" .
for snapshot in "$STAGING"/*.db; do
  [[ -e "$snapshot" ]] || continue
  tar -rf "$ARCHIVE" -C "$STAGING" "$(basename "$snapshot")"
done
gzip "$ARCHIVE"
echo "$ARCHIVE.gz"
