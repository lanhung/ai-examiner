#!/usr/bin/env bash
set -uo pipefail

umask 077
ROOT="/root/autodl-tmp/ai-examiner-mvp/ai-examiner-mvp-v0.4.0"
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

ollama_api_ready() {
  curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1
}

ollama_has_models() {
  curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags 2>/dev/null \
    | grep -Eq '"(name|model)":"'
}

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

if ! curl -fsS --max-time 3 http://127.0.0.1:6008/health >/dev/null 2>&1; then
  existing_pid=$(cat logs/uvicorn.pid 2>/dev/null || true)
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    for _ in $(seq 1 30); do
      curl -fsS --max-time 3 http://127.0.0.1:6008/health >/dev/null 2>&1 && break
      sleep 1
    done
  else
    stamp=$(date +%Y%m%d-%H%M%S)
    log="logs/uvicorn-6008-$stamp.log"
    nohup .venv/bin/uvicorn ai_examiner.main:app \
      --host 0.0.0.0 --port 6008 >"$log" 2>&1 &
    echo $! >logs/uvicorn.pid
    ln -sfn "$(basename "$log")" logs/uvicorn-6008.log
  fi
fi

for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:6008/health >/dev/null 2>&1; then
    echo "AI Examiner is ready on port 6008"
    exit 0
  fi
  sleep 1
done

echo "AI Examiner failed to become healthy; check $ROOT/logs/uvicorn-6008.log" >&2
exit 1
