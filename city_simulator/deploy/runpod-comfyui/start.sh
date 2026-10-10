#!/usr/bin/env bash
# Make sure ComfyUI is up on port 8188 for the app, and print the URL to put
# in .env. A ComfyUI that's already running (e.g. a ComfyUI pod template's) is
# left alone; otherwise this starts the one setup.sh installed, in the
# background (log: /workspace/logs/comfyui.log).
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

if up; then
  echo "ComfyUI: already running"
elif [ ! -x "$VENV/bin/python" ]; then
  echo "ComfyUI isn't running, and setup.sh didn't install one here. If the pod's template provides"
  echo "ComfyUI, start it from the template (or restart the pod); otherwise run setup.sh first."
  exit 1
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

In city_simulator/.env on the machine running the app -- for an image pod:

  VISUALS_IMAGE_PROVIDER=comfyui
  COMFYUI_IMAGE_URL=$URL

or for a video pod:

  VISUALS_VIDEO_PROVIDER=comfyui
  COMFYUI_VIDEO_URL=$URL

then restart the app. Stop ComfyUI with: bash $(dirname "$0")/stop.sh
MSG
