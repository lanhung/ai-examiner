#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ROOT/data/backups"
tar --exclude='backups' -czf "$ROOT/data/backups/ai-examiner-$STAMP.tar.gz" -C "$ROOT/data" .
echo "$ROOT/data/backups/ai-examiner-$STAMP.tar.gz"
