#!/usr/bin/env bash
# One-time (and after-every-pod-restart) setup for a RunPod pod -- or any
# Ubuntu + NVIDIA box. Idempotent: rerun it whenever the pod restarts
# (RunPod wipes everything outside /workspace; the venvs, models and repo
# live under /workspace, so a rerun only reinstalls the system packages).
#
#   bash deploy/runpod/setup.sh          then   bash deploy/runpod/start.sh
#
# Settings (environment variables, all optional):
#   VLLM_MODEL        default Qwen/Qwen3-30B-A3B-Instruct-2507-FP8
#   OLLAMA_CHAT_MODEL default llama3.1:8b (history generation, Ollama SCENE runs)
#   WORKSPACE         default /workspace (the pod's persistent volume)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WS="${WORKSPACE:-/workspace}"
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507-FP8}"
OLLAMA_CHAT_MODEL="${OLLAMA_CHAT_MODEL:-llama3.1:8b}"
export HF_HOME="${HF_HOME:-$WS/hf-cache}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$WS/ollama-models}"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== system packages"
$SUDO apt-get update -y
# build-essential + python3-dev + ninja: vLLM builds some GPU kernels just in
# time at startup, which needs a C compiler, Python.h and the ninja build tool.
$SUDO apt-get install -y --no-install-recommends curl git ca-certificates zstd python3-venv python3-dev \
  build-essential ninja-build lsof

echo "== Node 20 (to build the frontend)"
if ! command -v node >/dev/null || [ "$(node -v | tr -d v | cut -d. -f1)" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO bash -
  $SUDO apt-get install -y nodejs
fi

echo "== Ollama (embeddings + history generation)"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh

echo "== vLLM, in its own venv ($WS/vllm-venv)"
if [ ! -x "$WS/vllm-venv/bin/vllm" ]; then
  python3 -m venv "$WS/vllm-venv"
  "$WS/vllm-venv/bin/pip" install -U pip
  "$WS/vllm-venv/bin/pip" install vllm
fi
"$WS/vllm-venv/bin/pip" install -q ninja     # also inside the venv, which start.sh puts on PATH
if ! command -v nvcc >/dev/null && [ ! -x /usr/local/cuda/bin/nvcc ]; then
  echo "WARNING: no CUDA compiler (nvcc) found. vLLM may fail to build its kernels at startup;"
  echo "use a RunPod PyTorch template whose tag ends in '-devel', or start vLLM with"
  echo "VLLM_EXTRA_ARGS=--enforce-eager."
fi

echo "== the app's venv ($WS/app-venv)"
[ -x "$WS/app-venv/bin/python" ] || python3 -m venv "$WS/app-venv"
"$WS/app-venv/bin/pip" install -q -U pip
"$WS/app-venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "== frontend build"
(cd "$APP_DIR/frontend" && npm ci --no-audit --no-fund && npm run build)

echo "== .env"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
set_env() {  # set KEY=VALUE in .env, replacing an existing line
  if grep -q "^$1=" "$APP_DIR/.env"; then
    sed -i "s|^$1=.*|$1=$2|" "$APP_DIR/.env"
  else
    echo "$1=$2" >> "$APP_DIR/.env"
  fi
}
set_env OPENAI_COMPAT_BASE_URL "http://localhost:8000/v1"
set_env OLLAMA_CHAT_MODEL "$OLLAMA_CHAT_MODEL"

echo "== models (cached under $WS, so a pod restart doesn't re-download)"
if ! curl -s -o /dev/null http://localhost:11434/api/tags; then
  nohup ollama serve > "$WS/ollama.log" 2>&1 &
  for _ in $(seq 1 30); do curl -s -o /dev/null http://localhost:11434/api/tags && break; sleep 1; done
fi
ollama pull nomic-embed-text
ollama pull "$OLLAMA_CHAT_MODEL"
"$WS/vllm-venv/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('$VLLM_MODEL')"

echo
echo "Setup done. Start everything with:  bash $APP_DIR/deploy/runpod/start.sh"
