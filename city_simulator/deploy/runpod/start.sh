#!/usr/bin/env bash
# Start Ollama, vLLM and the app in the background (logs in /workspace/logs).
# Safe to rerun: anything already running is left alone.
#
# Settings (environment variables, all optional):
#   VLLM_MODEL         default Qwen/Qwen3-30B-A3B-Instruct-2507-FP8
#   VLLM_GPU_UTIL      default 0.80 -- the share of GPU memory vLLM takes;
#                      the rest is for Ollama (~6 GB)
#   VLLM_MAX_LEN       default 8192 -- context length
#   VLLM_WAIT_MIN      default 25 -- minutes to wait for vLLM to come up
#   VLLM_EXTRA_ARGS    extra `vllm serve` flags, e.g. "--enforce-eager" to skip
#                      the slow first-start compile (somewhat slower serving)
#   WORKSPACE          default /workspace
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WS="${WORKSPACE:-/workspace}"
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
export HF_HOME="${HF_HOME:-$WS/hf-cache}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$WS/ollama-models}"
# vLLM's compile caches (torch.compile, CUDA graphs, DeepGEMM kernels) default
# to ~/.cache, which RunPod wipes on restart -- keep them on the volume so the
# slow first-start compile only happens once.
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-$WS/vllm-cache}"
# vLLM's just-in-time kernel builds look for ninja and nvcc on PATH: put the
# venv's tools and the CUDA toolkit there (vLLM is started by full path, so
# the venv isn't otherwise "activated").
export PATH="$WS/vllm-venv/bin:/usr/local/cuda/bin:$PATH"
[ -d /usr/local/cuda ] && export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
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
    ${VLLM_EXTRA_ARGS:-} > "$LOGS/vllm.log" 2>&1 &
  VLLM_PID=$!
  echo -n "vLLM: starting $VLLM_MODEL (log: $LOGS/vllm.log) "
  WAIT_MIN="${VLLM_WAIT_MIN:-25}"
  for _ in $(seq 1 $((WAIT_MIN * 12))); do
    up http://localhost:8000/v1/models && break
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
      echo; echo "vLLM exited during startup. The engine's own error (the root cause):"; echo
      grep -E "EngineCore.*(Error|error|Exception|raise |No such file|not found|Traceback)" "$LOGS/vllm.log" \
        | grep -v "WARNING" | tail -n 25 || true
      echo; echo "The end of the log:"; tail -n 8 "$LOGS/vllm.log"
      echo; echo "Common fixes: apt-get install -y build-essential python3-dev ninja-build (Python.h / C compiler / ninja);"
      echo "VLLM_USE_DEEP_GEMM=0 bash $0 (DeepGEMM kernel build fails); VLLM_GPU_UTIL=0.7 (memory)."
      echo; echo "GPU right now:"; nvidia-smi --query-gpu=name,memory.used,memory.total,driver_version --format=csv
      exit 1
    fi
    echo -n "."; sleep 5
  done
  if up http://localhost:8000/v1/models; then
    echo " up"
  else
    echo; echo "vLLM still isn't answering after $WAIT_MIN min (it's still running as pid $VLLM_PID)."
    echo "Last log lines:"; tail -n 15 "$LOGS/vllm.log"
    echo "If it's still loading/compiling (the first start compiles kernels; later starts reuse"
    echo "$VLLM_CACHE_ROOT), wait and rerun this script -- it'll pick it up. To skip compiling:"
    echo "  pkill -f 'vllm serve'; VLLM_EXTRA_ARGS=--enforce-eager bash $0"
    exit 1
  fi
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
