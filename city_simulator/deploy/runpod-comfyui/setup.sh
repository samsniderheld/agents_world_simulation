#!/usr/bin/env bash
# Set up ComfyUI on a RunPod GPU pod as the app's image server (the app's
# ComfyUI provider calls its API). Idempotent: rerun it after every pod
# restart -- RunPod wipes everything outside /workspace, and ComfyUI, its
# Python packages and the models all live under /workspace, so a rerun only
# reinstalls system packages.
#
#   bash city_simulator/deploy/runpod-comfyui/setup.sh    then    start.sh
#
# Settings (environment variables, all optional):
#   COMFYUI_VERSION  default v0.39.0 -- a ComfyUI release tag (the Qwen-Image
#                    2.1 nodes need v0.37.0 or later), or "master" for the newest
#   WORKSPACE        default /workspace (the pod's persistent volume)
set -euo pipefail

WS="${WORKSPACE:-/workspace}"
COMFY="$WS/ComfyUI"
VENV="$WS/comfyui-venv"
VERSION="${COMFYUI_VERSION:-v0.39.0}"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== system packages"
$SUDO apt-get update -y
$SUDO apt-get install -y --no-install-recommends git wget curl ca-certificates python3-venv python3-dev lsof

echo "== ComfyUI $VERSION ($COMFY)"
[ -d "$COMFY/.git" ] || git clone -q https://github.com/comfyanonymous/ComfyUI "$COMFY"
git -C "$COMFY" fetch -q --tags origin
if [ "$VERSION" = "master" ]; then
  git -C "$COMFY" checkout -q master && git -C "$COMFY" pull -q
else
  git -C "$COMFY" checkout -q "$VERSION"
fi

echo "== Python packages ($VENV)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
# torch's CUDA 12.8 builds: RunPod's drivers run these; PyPI's default
# (CUDA 13) builds need a newer driver than many hosts have.
"$VENV/bin/pip" install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
"$VENV/bin/pip" install -q -r "$COMFY/requirements.txt"

echo "== Qwen-Image 2.1 models (~25 GB the first time; resumes if interrupted)"
REPO="https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main"
for f in diffusion_models/qwen_image_2.1_int8_convrot.safetensors \
         text_encoders/qwen3vl_8b_int8_convrot.safetensors \
         text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors \
         vae/qwen_image_2.1_vae_bf16.safetensors; do
  dest="$COMFY/models/$f"
  if [ -s "$dest" ]; then echo "  have $f"; continue; fi
  mkdir -p "$(dirname "$dest")"
  echo "  downloading $f"
  wget -q --show-progress -c -O "$dest.part" "$REPO/$f"
  mv "$dest.part" "$dest"
done

echo "== checking ComfyUI has every node the app's workflow uses"
for node in TextEncodeQwenImage21 QwenImage21Cache TextGenerate ComfySwitchNode SaveImageAdvanced \
            BatchImagesNode PrimitiveStringMultiline PreviewAny; do
  grep -rqs --include='*.py' "\"$node\"" "$COMFY/comfy_extras" "$COMFY/nodes.py" \
    || { echo "ComfyUI $VERSION has no $node node -- rerun with COMFYUI_VERSION=master"; exit 1; }
done

echo
echo "Done. Start ComfyUI with: bash $(dirname "$0")/start.sh"
