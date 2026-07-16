#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then echo "Usage: $0 BACKUP.tar.gz"; exit 2; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker compose down
mkdir -p "$ROOT/data"
tar -xzf "$1" -C "$ROOT/data"
docker compose up -d
