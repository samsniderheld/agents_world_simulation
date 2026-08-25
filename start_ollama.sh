#!/usr/bin/env bash
# Start the local Ollama server if it isn't already running.
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama is not installed. Install it with: brew install ollama" >&2
  exit 1
fi

if curl -s -o /dev/null http://localhost:11434/api/tags; then
  echo "Ollama is already running."
  exit 0
fi

if command -v brew >/dev/null 2>&1 && brew list --formula 2>/dev/null | grep -qx ollama; then
  brew services start ollama
else
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  disown
  echo "Started 'ollama serve' (pid $!); logs at /tmp/ollama.log"
fi

for _ in $(seq 1 20); do
  if curl -s -o /dev/null http://localhost:11434/api/tags; then
    echo "Ollama is up at http://localhost:11434"
    exit 0
  fi
  sleep 0.5
done

echo "Ollama did not come up within 10s." >&2
exit 1
