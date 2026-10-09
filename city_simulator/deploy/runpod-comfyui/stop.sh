#!/usr/bin/env bash
# Stop the ComfyUI that start.sh started (any job it's running is lost).
set -uo pipefail

# start.sh runs `<venv>/bin/python main.py --listen ...` from the ComfyUI folder
PATTERN="comfyui-venv/bin/python main.py --listen"
if ! pgrep -f "$PATTERN" >/dev/null; then echo "ComfyUI: not running"; exit 0; fi
pkill -TERM -f "$PATTERN"
for _ in $(seq 1 15); do
  pgrep -f "$PATTERN" >/dev/null || { echo "ComfyUI: stopped"; exit 0; }
  sleep 1
done
pkill -KILL -f "$PATTERN"
echo "ComfyUI: stopped (had to be killed)"
