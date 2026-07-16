#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then echo "Usage: $0 GIT_TAG_OR_COMMIT"; exit 2; fi
git checkout "$1"
docker compose build
docker compose up -d
