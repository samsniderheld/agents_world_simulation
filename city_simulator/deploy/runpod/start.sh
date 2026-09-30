#!/usr/bin/env bash
# Start Ollama, vLLM and the app in the background (logs in /workspace/logs).
# Safe to rerun: anything already running is left alone.
#
# Settings (environment variables, all optional):
#   VLLM_MODEL         default Qwen/Qwen3-30B-A3B-Instruct-2507-FP8
#   VLLM_GPU_UTIL      default 0.80 -- the share of GPU memory vLLM takes;
#                      the rest is for Ollama (~6 GB)
#   VLLM_MAX_LEN       default 8192 -- context length
#   WORKSPACE          default /workspace
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WS="${WORKSPACE:-/workspace}"
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
export HF_HOME="${HF_HOME:-$WS/hf-cache}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$WS/ollama-models}"
LOGS="$WS/logs"; mkdir -p "$LOGS"

up() { curl -s -o /dev/null "$1"; }

if up http://localhost:11434/api/tags; then
  echo "Ollama: already running"
else
  OLLAMA_NUM_PARALLEL=4 OLLAMA_MAX_LOADED_MODELS=2 nohup ollama serve > "$LOGS/ollama.log" 2>&1 &
  echo "Ollama: started (log: $LOGS/ollama.log)"
fi

if up http://localhost:8000/v1/models; then
  echo "vLLM: already running"
else
  nohup "$WS/vllm-venv/bin/vllm" serve "$VLLM_MODEL" --port 8000 \
    --max-model-len "${VLLM_MAX_LEN:-8192}" --gpu-memory-utilization "${VLLM_GPU_UTIL:-0.80}" \
    > "$LOGS/vllm.log" 2>&1 &
  echo -n "vLLM: starting $VLLM_MODEL (log: $LOGS/vllm.log) "
  for _ in $(seq 1 180); do up http://localhost:8000/v1/models && break; echo -n "."; sleep 5; done
  up http://localhost:8000/v1/models && echo " up" || { echo " not up after 15 min -- see $LOGS/vllm.log"; exit 1; }
fi

if up http://localhost:8420/; then
  echo "App: already running"
else
  (cd "$APP_DIR" && nohup "$WS/app-venv/bin/python" app.py > "$LOGS/app.log" 2>&1 &)
  sleep 3
  up http://localhost:8420/ && echo "App: running (log: $LOGS/app.log)" || echo "App: failed -- see $LOGS/app.log"
fi

cat <<MSG

The app listens on this pod's localhost only (it has no login). From your
laptop, tunnel it -- RunPod's "SSH over exposed TCP" gives the IP and port:

  ssh -L 8420:localhost:8420 root@<pod-ip> -p <ssh-port> -i ~/.ssh/<your-key>

then open http://localhost:8420.  Stop everything:  pkill -f 'vllm serve'; pkill -f app.py; pkill ollama
MSG
