#!/usr/bin/env bash
# Start the local Ollama server if it isn't already running.
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama is not installed. Install it with: brew install ollama" >&2
  exit 1
fi

# CITY mode sends many requests at once and keeps two models loaded (hero
# and background tier), so Ollama gets the active CITY hardware profile's
# parallelism (hardware.py's city_profile) and room for two models. Both
# are harmless for SCENE mode. Values already in the environment win.
cd "$(dirname "$0")"
PROFILE_PARALLEL=$(python3 -c 'import hardware; print(hardware.city_profile()["ollama_num_parallel"])' 2>/dev/null || echo 4)
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-$PROFILE_PARALLEL}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
if [ "$(uname)" = "Darwin" ] && command -v launchctl >/dev/null 2>&1; then
  # `brew services` starts Ollama through launchd, which doesn't see this
  # shell's environment.
  launchctl setenv OLLAMA_NUM_PARALLEL "$OLLAMA_NUM_PARALLEL" || true
  launchctl setenv OLLAMA_MAX_LOADED_MODELS "$OLLAMA_MAX_LOADED_MODELS" || true
fi

if curl -s -o /dev/null http://localhost:11434/api/tags; then
  echo "Ollama is already running. (Restart it to apply OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL, OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS.)"
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
    echo "Ollama is up at http://localhost:11434 (OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL, OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS)"
    exit 0
  fi
  sleep 0.5
done

echo "Ollama did not come up within 10s." >&2
exit 1
