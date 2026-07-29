#!/usr/bin/env bash
set -uo pipefail

umask 077
ROOT="${AI_EXAMINER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OLLAMA_MODELS="${OLLAMA_MODELS:-/root/autodl-tmp/ollama-models}"
export OLLAMA_MODELS

for _ in $(seq 1 60); do
  [[ -d "$ROOT" ]] && break
  sleep 2
done

if [[ ! -d "$ROOT" ]]; then
  echo "AI Examiner project directory is unavailable: $ROOT" >&2
  exit 1
fi

cd "$ROOT"
mkdir -p logs

PORT="${APP_PORT:-}"
PROVIDER="${MODEL_PROVIDER:-}"
if [[ -z "$PORT" && -f .env ]]; then
  PORT="$(sed -nE 's/^APP_PORT=([0-9]+)$/\1/p' .env | tail -1)"
fi
if [[ -z "$PROVIDER" && -f .env ]]; then
  PROVIDER="$(sed -nE 's/^MODEL_PROVIDER=([a-z0-9_-]+)$/\1/p' .env | tail -1)"
fi
PORT="${PORT:-6008}"
PROVIDER="${PROVIDER:-mock}"
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "Invalid APP_PORT: $PORT" >&2
  exit 1
fi

ollama_api_ready() {
  curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1
}

ollama_has_models() {
  curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags 2>/dev/null \
    | grep -Eq '"(name|model)":"'
}

if [[ "$PROVIDER" == "ollama" ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "MODEL_PROVIDER=ollama but the ollama executable is unavailable" >&2
    exit 1
  fi
  start_ollama=false
  if ! ollama_api_ready; then
    start_ollama=true
  elif ! ollama_has_models && find "$OLLAMA_MODELS/manifests" -type f -print -quit \
    2>/dev/null | grep -q .; then
    existing_ollama_pid=$(pgrep -xo ollama || true)
    if [[ -n "$existing_ollama_pid" ]]; then
      kill "$existing_ollama_pid"
      for _ in $(seq 1 30); do
        kill -0 "$existing_ollama_pid" 2>/dev/null || break
        sleep 1
      done
    fi
    start_ollama=true
  fi

  if [[ "$start_ollama" == true ]]; then
    nohup ollama serve >logs/ollama.log 2>&1 &
    echo $! >logs/ollama.pid
    for _ in $(seq 1 60); do
      ollama_has_models && break
      sleep 1
    done
  fi
fi

if ! curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  existing_pid=$(cat logs/uvicorn.pid 2>/dev/null || true)
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    for _ in $(seq 1 30); do
      curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
      sleep 1
    done
  else
    stamp=$(date +%Y%m%d-%H%M%S)
    log="logs/uvicorn-$PORT-$stamp.log"
    nohup .venv/bin/uvicorn ai_examiner.main:app \
      --host 0.0.0.0 --port "$PORT" >"$log" 2>&1 &
    echo $! >logs/uvicorn.pid
    ln -sfn "$(basename "$log")" "logs/uvicorn-$PORT.log"
  fi
fi

for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "AI Examiner is ready on port $PORT"
    exit 0
  fi
  sleep 1
done

echo "AI Examiner failed to become healthy; check $ROOT/logs/uvicorn-$PORT.log" >&2
exit 1
