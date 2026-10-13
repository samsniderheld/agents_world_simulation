#!/usr/bin/env bash
# Get a RunPod pod's ComfyUI ready to be the app's image or video server: the
# workflow's models where that ComfyUI looks for them, and a check that it has
# every node the workflow uses. Idempotent -- rerun it any time (models
# already there are skipped; an interrupted download resumes).
#
#   bash city_simulator/deploy/runpod-comfyui/setup.sh          # image pod (Qwen-Image 2.1, ~25 GB)
#   bash city_simulator/deploy/runpod-comfyui/setup.sh video    # video pod (MiniMax H3, ~62 GB)
#
# Which ComfyUI, in order:
#   1. COMFYUI_DIR, if set (a ComfyUI folder);
#   2. the ComfyUI running on port 8188 (e.g. a ComfyUI pod template's) --
#      the models go in the folders it reports, the same place its own model
#      downloads in the web UI go;
#   3. a ComfyUI already on the volume (/workspace/runpod-slim/ComfyUI, the
#      RunPod ComfyUI template's, or /workspace/ComfyUI);
#   4. otherwise a new one is installed at /workspace/ComfyUI (then start it
#      with start.sh).
#
# Settings (environment variables, all optional):
#   COMFYUI_DIR      use this ComfyUI folder
#   MINIMAX_TEXT_ENCODER  video: nvfp4 (default, the workflow's; made for Blackwell
#                    GPUs) or int8 (27 GB; then set the workflow to use it -- see
#                    visuals/data/config.yaml's video_workflow)
#   COMFYUI_VERSION  for a new install or an update: a release tag (default
#                    v0.39.2; the Qwen-Image 2.1 nodes need v0.37.0+) or "master"
#   COMFYUI_UPDATE   1: if the existing ComfyUI is missing the workflow's nodes,
#                    update it to COMFYUI_VERSION (then exit 3: restart ComfyUI --
#                    e.g. restart the pod -- and rerun). pods.py sets this.
#   WORKSPACE        default /workspace
set -euo pipefail

WS="${WORKSPACE:-/workspace}"
API="http://localhost:8188"
VERSION="${COMFYUI_VERSION:-v0.39.2}"
MODE="${1:-image}"
case "$MODE" in
  image)   # visuals/data/comfyui/qwen_image_2_1_edit.json
    LABEL="Qwen-Image 2.1 (~25 GB)"
    NODES="TextEncodeQwenImage21 QwenImage21Cache TextGenerate ComfySwitchNode SaveImageAdvanced BatchImagesNode PrimitiveStringMultiline PreviewAny"
    REPO="https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main"
    MODELS="diffusion_models/qwen_image_2.1_int8_convrot.safetensors
text_encoders/qwen3vl_8b_int8_convrot.safetensors
text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors
vae/qwen_image_2.1_vae_bf16.safetensors" ;;
  video)   # visuals/data/comfyui/minimax_h3_i2v.json and minimax_h3_r2v_turbo.json
    LABEL="MiniMax H3 (~62 GB)"
    NODES="MiniMaxH3ImageToVideo MiniMaxH3ReferenceToVideo ModelAttentionBackend LoraLoaderModelOnly ResolutionSelector CreateVideo SaveVideo ComfyMathExpression VAEDecodeAudio PrimitiveFloat PrimitiveStringMultiline SamplerCustomAdvanced BasicGuider BasicScheduler KSamplerSelect RandomNoise"
    REPO="https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main"
    TE="qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    [ "${MINIMAX_TEXT_ENCODER:-nvfp4}" = "int8" ] && TE="qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
    # the reference-to-video turbo LoRA isn't in Comfy-Org's repo -- a full URL after the name says where it is
    MODELS="diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors
diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors
loras/minimax_h3_turbo_4step_pruned_comfyui.safetensors https://huggingface.co/drbaph/MiniMax-H3-Turbo-Lora-ComfyUI/resolve/main/minimax_h3_turbo_4step_pruned_comfyui.safetensors
text_encoders/$TE
vae/minimax_h3_video_vae_fp16.safetensors
vae/minimax_h3_audio_vae_fp32.safetensors" ;;
  *) echo "usage: $0 [image|video]"; exit 2 ;;
esac
running() { curl -s -o /dev/null --max-time 3 "$API/system_stats"; }

# --- which ComfyUI -------------------------------------------------------------------
COMFY=""
if [ -n "${COMFYUI_DIR:-}" ]; then
  COMFY="$COMFYUI_DIR"; echo "== using COMFYUI_DIR: $COMFY"
elif running; then
  echo "== using the ComfyUI running on port 8188"
else
  for d in "$WS/runpod-slim/ComfyUI" "$WS/ComfyUI"; do
    [ -f "$d/main.py" ] && { COMFY="$d"; echo "== using the ComfyUI at $COMFY (not running right now)"; break; }
  done
fi

if [ -z "$COMFY" ] && ! running; then
  # Nothing on the pod: install one (start it with start.sh).
  COMFY="$WS/ComfyUI"; VENV="$WS/comfyui-venv"
  SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  echo "== no ComfyUI found: installing ComfyUI $VERSION at $COMFY"
  $SUDO apt-get update -y
  $SUDO apt-get install -y --no-install-recommends git wget curl ca-certificates python3-venv python3-dev lsof
  [ -d "$COMFY/.git" ] || git clone -q https://github.com/comfyanonymous/ComfyUI "$COMFY"
  git -C "$COMFY" fetch -q --tags origin
  if [ "$VERSION" = "master" ]; then git -C "$COMFY" checkout -q master && git -C "$COMFY" pull -q
  else git -C "$COMFY" checkout -q "$VERSION"; fi
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  # torch's CUDA 12.8 builds: RunPod's drivers run these; PyPI's default
  # (CUDA 13) builds need a newer driver than many hosts have.
  "$VENV/bin/pip" install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
  "$VENV/bin/pip" install -q -r "$COMFY/requirements.txt"
fi

# --- where its models go -------------------------------------------------------------------
# A running ComfyUI says where it reads each kind of model (its own
# models/<kind> folder first); otherwise it's <ComfyUI>/models/<kind>.
model_dir() {
  local kind="$1"
  if [ -z "$COMFY" ] && running; then
    curl -s --max-time 10 "$API/internal/folder_paths" | python3 -c "
import json, sys
paths = json.load(sys.stdin).get('$kind') or [[]]
paths = paths[0] if paths and isinstance(paths[0], list) else paths
own = [p for p in paths if p.rstrip('/').endswith('/models/$kind')]
print((own or paths)[0])"
  else
    echo "$COMFY/models/$kind"
  fi
}

echo "== $LABEL models"
echo "$MODELS" | while read -r f src; do
  kind="${f%%/*}"; name="${f#*/}"
  dir="$(model_dir "$kind")"; dest="$dir/$name"
  if [ -s "$dest" ]; then echo "  have $dest"; continue; fi
  mkdir -p "$dir"
  echo "  downloading $name -> $dir"
  wget -q --show-progress -c -O "$dest.part" "${src:-$REPO/$f}"
  mv "$dest.part" "$dest"
done

# --- does it have the workflow's nodes? --------------------------------------------------
echo "== checking ComfyUI has every node the app's workflow uses"
missing=""
for node in $NODES; do
  if running; then
    curl -s --max-time 10 "$API/object_info/$node" | grep -q "\"$node\"" || missing="$missing $node"
  else
    grep -rqs --include='*.py' "\"$node\"" "$COMFY/comfy_extras" "$COMFY/nodes.py" || missing="$missing $node"
  fi
done
if [ -n "$missing" ]; then
  echo "This ComfyUI is missing:$missing"
  dir="${COMFY:-${COMFYUI_DIR:-$WS/runpod-slim/ComfyUI}}"
  if [ "${COMFYUI_UPDATE:-}" = "1" ] && [ -d "$dir/.git" ]; then
    echo "== updating the ComfyUI in $dir to $VERSION"
    git -C "$dir" fetch -q --tags origin
    if [ "$VERSION" = "master" ]; then git -C "$dir" checkout -q master && git -C "$dir" pull -q
    else git -C "$dir" checkout -q "$VERSION"; fi
    # its own Python: the RunPod template's venv, else the one setup.sh made, else the system's
    py=python3
    for v in "$dir/.venv-cu128" "$dir/.venv" "$WS/comfyui-venv"; do
      [ -x "$v/bin/python" ] && { py="$v/bin/python"; break; }
    done
    "$py" -m pip install -q -r "$dir/requirements.txt"
    echo "Updated. Restart ComfyUI (restart the pod), then rerun this script to check."
    exit 3
  fi
  echo "Update ComfyUI (ComfyUI Manager -> Update ComfyUI, or git pull in its folder; the Qwen-Image 2.1"
  echo "nodes need 0.37.0+, MiniMax H3 0.39.0+), restart it, then rerun this script."
  exit 1
fi
running && echo "  all there ($(curl -s --max-time 5 "$API/system_stats" | python3 -c 'import json,sys; print("ComfyUI", json.load(sys.stdin)["system"].get("comfyui_version"))'))" \
        || echo "  all there"

echo
if running; then
  echo "Done. ComfyUI is running; restart it if it was running while models were downloaded"
  echo "(new models show up after a refresh). Then see start.sh's output for the URL to use."
else
  echo "Done. Start ComfyUI with: bash $(dirname "$0")/start.sh"
fi
