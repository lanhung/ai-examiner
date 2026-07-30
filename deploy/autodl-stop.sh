#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_EXAMINER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PID_FILE="$ROOT/logs/uvicorn.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "AI Examiner is already stopped (PID file not found)"
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
  rm -f "$PID_FILE"
  echo "Removed invalid Uvicorn PID file"
  exit 0
fi

if ! kill -0 "$pid" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "AI Examiner is already stopped (stale PID $pid)"
  exit 0
fi

command_line="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
if [[ "$command_line" != *"uvicorn ai_examiner.main:app"* ]]; then
  echo "Refusing to stop PID $pid because it is not AI Examiner Uvicorn" >&2
  exit 1
fi

kill "$pid"
for _ in $(seq 1 30); do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "AI Examiner stopped"
    exit 0
  fi
  sleep 1
done

kill -KILL "$pid"
rm -f "$PID_FILE"
echo "AI Examiner required SIGKILL after graceful shutdown timeout"
