#!/usr/bin/env bash
# Restart just the web app -- e.g. after a git pull. vLLM, Ollama and the
# ComfyUI pods are left alone.
#
#   bash deploy/runpod/restart.sh            # restart the app
#   bash deploy/runpod/restart.sh --pull     # git pull first, then restart
#   bash deploy/runpod/restart.sh --force    # even mid-generation / mid-run
#
# Like stop.sh, it won't stop the app while a city is generating, a
# simulation is running or an image/video is being made, unless --force.
# The frontend is rebuilt first if its source changed.
set -uo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WS="${WORKSPACE:-/workspace}"
LOGS="$WS/logs"
PULL=0; STOP_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --pull) PULL=1 ;;
    --force|-f) STOP_ARGS+=(--force) ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (expected --pull or --force)"; exit 2 ;;
  esac
done
up() { curl -s -o /dev/null "$1"; }
mkdir -p "$LOGS"

if [ $PULL -eq 1 ]; then
  (cd "$APP_DIR" && git pull --ff-only) || { echo "git pull failed -- app not restarted"; exit 1; }
fi

bash "$(dirname "$0")/stop.sh" app ${STOP_ARGS[@]+"${STOP_ARGS[@]}"}
if up http://localhost:8420/; then
  echo "App: still running -- not restarted."
  exit 1
fi

# The browser gets frontend/'s built copy (static/dist): rebuild if the source is newer.
DIST="$APP_DIR/static/dist/index.html"
if [ ! -f "$DIST" ] || [ -n "$(find "$APP_DIR/frontend/src" "$APP_DIR/frontend/package.json" -newer "$DIST" -print -quit)" ]; then
  echo "Frontend: source changed, rebuilding..."
  (cd "$APP_DIR/frontend" && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null) \
    && echo "Frontend: rebuilt (hard-refresh the browser)" || echo "Frontend: build FAILED -- run: cd $APP_DIR/frontend && npm run build"
fi

(cd "$APP_DIR" && nohup "$WS/app-venv/bin/python" app.py > "$LOGS/app.log" 2>&1 &)
for _ in $(seq 1 15); do up http://localhost:8420/ && break; sleep 1; done
if up http://localhost:8420/; then
  echo "App: running (log: $LOGS/app.log)"
else
  echo "App: failed to start -- last log lines:"; tail -n 15 "$LOGS/app.log"; exit 1
fi
