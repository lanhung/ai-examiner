#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="${AI_EXAMINER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"
command -v curl >/dev/null
command -v ollama >/dev/null

ready() {
  curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1
}

if ready; then
  echo "Ollama is already available at 127.0.0.1:11434."
  exit 0
fi

mkdir -p logs
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="${OLLAMA_MODELS:-/root/autodl-tmp/ollama-models}"
if [[ ! -d "$OLLAMA_MODELS" ]]; then
  echo "Model directory missing: $OLLAMA_MODELS" >&2
  exit 1
fi
nohup ollama serve >>logs/ollama.log 2>&1 </dev/null &
pid=$!
printf '%s\n' "$pid" >logs/ollama.pid
for _ in {1..60}; do
  if ready; then
    echo "Ollama is ready at 127.0.0.1:11434; models: $OLLAMA_MODELS"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "Ollama exited. Inspect logs/ollama.log." >&2
    exit 1
  fi
  sleep 1
done
echo "Ollama readiness timed out. Inspect logs/ollama.log." >&2
exit 1
