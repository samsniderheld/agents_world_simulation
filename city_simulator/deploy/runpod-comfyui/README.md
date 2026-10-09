# ComfyUI worker for RunPod Serverless (Qwen-Image 2.1)

The image the app's ComfyUI provider (`visuals/providers/comfyui.py`) needs
behind a RunPod Serverless endpoint to run `visuals/data/comfyui/qwen_image_2_1_edit.json`.

**Why a custom image:** RunPod's stock `worker-comfyui` image ships ComfyUI
0.34.0, which has no `TextEncodeQwenImage21` / `QwenImage21Cache` nodes (they
arrived in 0.37.0), and no Qwen models -- so jobs fail with
`Node 'Qwen Image 2.1 Cache' not found`. This `Dockerfile` starts from that
same worker (so the request format the app sends is unchanged), upgrades
ComfyUI to v0.39.0, checks every node the workflow uses is present, and bakes
in the four model files:

| folder | file | size |
|---|---|---|
| `models/diffusion_models` | `qwen_image_2.1_int8_convrot.safetensors` | 6.8 GB |
| `models/text_encoders` | `qwen3vl_8b_int8_convrot.safetensors` | 8.7 GB |
| `models/text_encoders` | `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | 8.8 GB (the prompt enhancer) |
| `models/vae` | `qwen_image_2.1_vae_bf16.safetensors` | 0.6 GB |

The finished image is about 40 GB.

`handler.py` is the worker's entry point: RunPod's GitHub builder refuses a
repo without a `runpod.serverless.start(...)` handler, so the Dockerfile moves
worker-comfyui's own handler aside and `handler.py` loads and starts it --
the worker behaves exactly like the stock one.

## Deploy

**Option A -- let RunPod build it (no Docker needed).** In the RunPod console:
*Serverless -> New Endpoint -> GitHub repo*, connect GitHub, pick this repo
and branch, and set

- Dockerfile path: `city_simulator/deploy/runpod-comfyui/Dockerfile`
- Build context: `city_simulator/deploy/runpod-comfyui`

RunPod builds the image and deploys it; a push to that branch rebuilds it.

**Option B -- build it yourself** on a Linux x86-64 machine with Docker (an
Apple Silicon Mac would have to emulate x86, which is very slow at this size):

```bash
cd city_simulator/deploy/runpod-comfyui
docker build --platform linux/amd64 -t <dockerhub-user>/comfyui-qwen21:1 .
docker push <dockerhub-user>/comfyui-qwen21:1
```

then create (or edit) the Serverless endpoint with that image.

Build arguments, if you need them: `COMFYUI_VERSION` (default `0.39.0`;
anything >= 0.37.0 has the Qwen-Image 2.1 nodes) and `WORKER_BASE` (default
`runpod/worker-comfyui:5.10.0-base`).

## Endpoint settings

- **GPU:** 48 GB recommended (L40S, RTX 6000 Ada, A6000) -- the models are
  ~25 GB of weights. A 24 GB card may work with ComfyUI swapping models
  between the encoder, prompt enhancer and sampler, but slower.
- **Container disk:** at least 60 GB.
- **Idle timeout / active workers:** a cold start loads ~25 GB of models; one
  active (always-on) worker avoids that wait at the cost of paying for it.

## Point the app at it

In `city_simulator/.env`:

```
VISUALS_PROVIDER=comfyui
COMFYUI_URL=https://api.runpod.ai/v2/<endpoint id>
RUNPOD_API_KEY=<key>
```

and restart the app. A missing node or model now shows up in the image
build, not as a failed job.

**If the build is too big for RunPod's GitHub builder:** build without step 4
of the Dockerfile and put the models on a network volume attached to the
endpoint instead. The worker reads a volume's `models/unet` (ComfyUI's older
name for `diffusion_models`), `models/clip` (for `text_encoders`) and
`models/vae` -- so the files go in `/runpod-volume/models/unet/`,
`/runpod-volume/models/clip/` and `/runpod-volume/models/vae/`. A volume ties
the endpoint to that volume's data center.
