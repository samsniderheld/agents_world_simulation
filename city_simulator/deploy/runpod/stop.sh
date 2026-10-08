#!/usr/bin/env bash
# Stop what start.sh started: the app, vLLM and Ollama.
#
#   bash deploy/runpod/stop.sh                # everything
#   bash deploy/runpod/stop.sh app            # just the app (e.g. to pick up a git pull)
#   bash deploy/runpod/stop.sh vllm           # just vLLM (e.g. to serve another model)
#   bash deploy/runpod/stop.sh app vllm       # any combination of: app vllm ollama
#   bash deploy/runpod/stop.sh --force        # stop the app even mid-generation / mid-run
#
# The app isn't stopped while a city is generating or a simulation is
# running (that work would be lost) unless you pass --force. Each process
# gets a few seconds to exit cleanly, then is killed. Start again with
# start.sh -- it only starts what isn't already running.
set -uo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FORCE=0
WANT=()
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    app|vllm|ollama) WANT+=("$arg") ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (expected app, vllm, ollama or --force)"; exit 2 ;;
  esac
done
[ ${#WANT[@]} -eq 0 ] && WANT=(app vllm ollama)
wants() { [[ " ${WANT[*]} " == *" $1 "* ]]; }

# stop <label> <pkill -f pattern>...: TERM, wait up to 15 s, then KILL.
stop() {
  local label="$1"; shift
  local found=0
  for pattern in "$@"; do pgrep -f "$pattern" >/dev/null && found=1; done
  if [ $found -eq 0 ]; then echo "$label: not running"; return; fi
  for pattern in "$@"; do pkill -TERM -f "$pattern" 2>/dev/null; done
  for _ in $(seq 1 15); do
    local alive=0
    for pattern in "$@"; do pgrep -f "$pattern" >/dev/null && alive=1; done
    [ $alive -eq 0 ] && { echo "$label: stopped"; return; }
    sleep 1
  done
  for pattern in "$@"; do pkill -KILL -f "$pattern" 2>/dev/null; done
  echo "$label: stopped (had to be killed)"
}

if wants app && [ $FORCE -eq 0 ] && curl -s -o /dev/null http://localhost:8420/ 2>/dev/null; then
  # The app may have a login (APP_PASSWORD in .env); use it for the status checks.
  AUTH=()
  if [ -f "$APP_DIR/.env" ]; then
    PASS="$(grep -E '^APP_PASSWORD=' "$APP_DIR/.env" | tail -n1 | cut -d= -f2- | tr -d '"'"'")"
    USER_="$(grep -E '^APP_USER=' "$APP_DIR/.env" | tail -n1 | cut -d= -f2- | tr -d '"'"'")"
    [ -n "$PASS" ] && AUTH=(-u "${USER_:-admin}:$PASS")
  fi
  busy=()
  curl -s "${AUTH[@]}" http://localhost:8420/api/history/status | grep -q '"phase": *"running"' && busy+=("a city is generating")
  curl -s "${AUTH[@]}" http://localhost:8420/api/agents/state | grep -q '"phase": *"running"' && busy+=("a simulation is running")
  if [ ${#busy[@]} -gt 0 ]; then
    reason="${busy[0]}"; [ ${#busy[@]} -gt 1 ] && reason="$reason and ${busy[1]}"
    echo "App: not stopped -- $reason; its work would be lost."
    echo "     Wait for it to finish, or rerun with --force."
    WANT=("${WANT[@]/app}")
  fi
fi

wants app && stop "App" "python app.py"
wants vllm && stop "vLLM" "vllm serve" "VLLM::EngineCore"
# Ollama's server, plus the model runners it spawns (they hold the GPU memory).
wants ollama && stop "Ollama" "ollama serve" "lib/ollama/llama-server" "ollama runner"

if command -v nvidia-smi >/dev/null; then
  echo
  echo "GPU memory now: $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
fi
