# A RunPod Serverless ComfyUI worker that can run the app's Qwen-Image 2.1
# edit workflow (visuals/data/comfyui/qwen_image_2_1_edit.json). See README.md
# in this folder for building and deploying it.
#
# Build context: this folder (RunPod's GitHub builder uses the Dockerfile's
# folder).
#
# RunPod's worker-comfyui base image (which speaks the request format the
# app's ComfyUI provider sends) ships ComfyUI 0.34.0, but the workflow's
# TextEncodeQwenImage21 and QwenImage21Cache nodes only arrived in ComfyUI
# 0.37.0 -- so this upgrades ComfyUI in place and adds the four Qwen-Image 2.1
# model files (~25 GB).

ARG WORKER_BASE=runpod/worker-comfyui:5.10.0-base
FROM ${WORKER_BASE}

ARG COMFYUI_VERSION=0.39.0

# 1. ComfyUI at the wanted release. The base image's /comfyui is normally a
#    git checkout (comfy-cli clones it); if it isn't, make it one.
RUN set -eux; \
    cd /comfyui; \
    if [ ! -d .git ]; then \
      git init -q; \
      git remote add origin https://github.com/comfyanonymous/ComfyUI.git; \
    fi; \
    git fetch -q --depth 1 origin "refs/tags/v${COMFYUI_VERSION}:refs/tags/v${COMFYUI_VERSION}"; \
    git checkout -q -f "v${COMFYUI_VERSION}"

# 2. Its dependencies, into the venv the worker launches ComfyUI with
#    (/opt/venv) -- the same steps and pins as the base image's own Dockerfile:
#    torch first as +cu128 builds (RunPod hosts' drivers can't run PyPI's cu13
#    wheels), then requirements.txt, then transformers/huggingface-hub capped
#    below their breaking majors.
RUN set -eux; \
    uv pip install --python /opt/venv/bin/python \
      torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
      --index-url https://download.pytorch.org/whl/cu128; \
    uv pip install --python /opt/venv/bin/python -r /comfyui/requirements.txt; \
    for r in /comfyui/custom_nodes/*/requirements.txt; do \
      [ -f "$r" ] && uv pip install --python /opt/venv/bin/python -r "$r" || true; \
    done; \
    uv pip install --python /opt/venv/bin/python "transformers>=4.50.3,<5" "huggingface-hub<1.0"

# 3. Fail the build (not a job, later) if any node the workflow uses is
#    missing, then start ComfyUI once on CPU to prove the whole node graph
#    imports -- the base image's own smoke test.
RUN set -eux; \
    for node in TextEncodeQwenImage21 QwenImage21Cache TextGenerate ComfySwitchNode SaveImageAdvanced \
                BatchImagesNode PrimitiveStringMultiline PreviewAny; do \
      grep -rqs --include='*.py' "\"$node\"" /comfyui/comfy_extras /comfyui/nodes.py \
        || { echo "ComfyUI v${COMFYUI_VERSION} has no $node node -- raise COMFYUI_VERSION"; exit 1; }; \
    done; \
    cd /comfyui && timeout 300 /opt/venv/bin/python main.py --quick-test-for-ci --cpu

# 4. The Qwen-Image 2.1 models (Comfy-Org's int8 builds, as the workflow names
#    them), in the folders ComfyUI's loaders read.
ARG QWEN_REPO=https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main
RUN set -eux; \
    cd /comfyui/models; \
    for f in diffusion_models/qwen_image_2.1_int8_convrot.safetensors \
             text_encoders/qwen3vl_8b_int8_convrot.safetensors \
             text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors \
             vae/qwen_image_2.1_vae_bf16.safetensors; do \
      mkdir -p "$(dirname "$f")"; \
      wget -q -O "$f" "${QWEN_REPO}/$f"; \
      [ -s "$f" ] || { echo "download failed: $f"; exit 1; }; \
    done; \
    ls -la diffusion_models text_encoders vae

# 5. The entry point: worker-comfyui's own handler, moved aside and started by
#    handler.py. (RunPod's GitHub builder also wants a runpod.serverless.start()
#    handler at the top of the repo, so the repo root has an identical copy --
#    tests/test_runpod_worker.py keeps the two the same.)
RUN mv /handler.py /worker_comfyui_handler.py
COPY handler.py /handler.py
