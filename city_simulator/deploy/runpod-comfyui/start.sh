#!/usr/bin/env bash
# Start ComfyUI on the pod in the background, listening on port 8188 for the
# app (log: /workspace/logs/comfyui.log). Safe to rerun: leaves a running
# ComfyUI alone. Run setup.sh first (and again after a pod restart).
#
# Expose port 8188 in the pod's settings (Edit Pod -> Expose HTTP Ports); the
# app then reaches it at https://<pod id>-8188.proxy.runpod.net. There is no
# password: anyone with that URL can use the GPU while the pod runs.
set -euo pipefail

WS="${WORKSPACE:-/workspace}"
COMFY="$WS/ComfyUI"
VENV="$WS/comfyui-venv"
LOGS="$WS/logs"; mkdir -p "$LOGS"
up() { curl -s -o /dev/null --max-time 3 http://localhost:8188/system_stats; }

[ -x "$VENV/bin/python" ] || { echo "No ComfyUI install yet -- run setup.sh first."; exit 1; }

if up; then
  echo "ComfyUI: already running"
else
  (cd "$COMFY" && nohup "$VENV/bin/python" main.py --listen 0.0.0.0 --port 8188 > "$LOGS/comfyui.log" 2>&1 &)
  echo -n "ComfyUI: starting (log: $LOGS/comfyui.log) "
  for _ in $(seq 1 60); do up && break; echo -n "."; sleep 5; done
  if up; then echo " up"; else
    echo; echo "ComfyUI didn't come up within 5 minutes. The end of its log:"; tail -n 25 "$LOGS/comfyui.log"; exit 1
  fi
fi

URL="https://${RUNPOD_POD_ID:-<pod id>}-8188.proxy.runpod.net"
cat <<MSG

In city_simulator/.env on the machine running the app:

  VISUALS_PROVIDER=comfyui
  COMFYUI_URL=$URL

then restart the app. Stop ComfyUI with: bash $(dirname "$0")/stop.sh
MSG
