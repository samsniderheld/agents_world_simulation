#!/usr/bin/env bash
# Stop the local Ollama server, however it was started.
set -euo pipefail

if command -v brew >/dev/null 2>&1 && brew services list 2>/dev/null | grep -q '^ollama\s'; then
  brew services stop ollama
  exit 0
fi

if pkill -f "ollama serve" 2>/dev/null; then
  echo "Stopped 'ollama serve'."
else
  echo "No running ollama server found."
fi
