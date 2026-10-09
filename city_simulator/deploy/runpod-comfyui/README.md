# ComfyUI on a RunPod pod (images for the app)

Runs ComfyUI on a RunPod GPU pod as an API the app calls for every image
generate/edit (`visuals/providers/comfyui.py`), with the Qwen-Image 2.1
image-edit workflow (`visuals/data/comfyui/qwen_image_2_1_edit.json`). Once
it's started it stays up -- no per-request cold start.

## 1. The pod

- **GPU:** 48 GB recommended (L40S, RTX 6000 Ada, A6000, A100). The models
  are ~25 GB of weights; a 24 GB card may work with ComfyUI swapping them, slower.
- **Template:** RunPod's ComfyUI template is easiest (its ComfyUI, in
  `/workspace/runpod-slim/ComfyUI`, starts with the pod). Any PyTorch / Ubuntu
  image works too -- `setup.sh` then installs ComfyUI itself.
- **Volume:** 60 GB+ at `/workspace` (ComfyUI and the models live there, so
  they survive pod restarts).
- **Expose HTTP Ports:** `8188`.

## 2. Models and a check

In the pod's terminal (Jupyter or SSH):

```bash
cd /workspace
git clone https://github.com/samsniderheld/agents_world_simulation.git   # once
cd agents_world_simulation && git checkout comfyui_pod
bash city_simulator/deploy/runpod-comfyui/setup.sh
bash city_simulator/deploy/runpod-comfyui/start.sh
```

`setup.sh` finds the pod's ComfyUI -- the one running on port 8188, else
one on the volume -- and puts the four models in the folders that ComfyUI
reads them from (the same place its web UI's model downloads go; models
already there are skipped). Then it checks ComfyUI has every node the
workflow uses: the Qwen-Image 2.1 nodes need ComfyUI 0.37.0+, so an older
install gets a clear message to update it. Only on a pod with no ComfyUI at
all does it install one (v0.39.0 at `/workspace/ComfyUI`;
`COMFYUI_VERSION=master` for the newest, `COMFYUI_DIR` to pick a folder).

`start.sh` makes sure ComfyUI is up and prints the URL to use; it only
starts a ComfyUI that `setup.sh` installed (a template's runs on its own).
`stop.sh` stops that one.

## 3. Point the app at it

In `city_simulator/.env` on the machine running the app:

```
VISUALS_PROVIDER=comfyui
COMFYUI_URL=https://<pod id>-8188.proxy.runpod.net
```

then restart the app. Image and storyboard-frame nodes now run on the pod;
video and music nodes still use fal.

**Size:** the Image node's aspect ratio and **1K / 2K** pickers set the
output: 1K is about 1 megapixel (16:9 = 1376 x 768), 2K about 4 (2720 x
1536) -- also when reference images are wired in (their pixel budget follows
the same setting).

**No password:** ComfyUI has no login, so anyone who has the pod's URL can
run jobs on it while it's up. Stop the pod when you're done (that also stops
the billing).

## Models

| folder | file | size |
|---|---|---|
| `models/diffusion_models` | `qwen_image_2.1_int8_convrot.safetensors` | 6.8 GB |
| `models/text_encoders` | `qwen3vl_8b_int8_convrot.safetensors` | 8.7 GB |
| `models/text_encoders` | `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | 8.8 GB (prompt enhancer) |
| `models/vae` | `qwen_image_2.1_vae_bf16.safetensors` | 0.6 GB |

From [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1).

## Another workflow

Export it from ComfyUI with *Export (API)* into `visuals/data/comfyui/`, and
describe it in `visuals/data/config.yaml`'s `comfyui` section (where its
prompt, seed, size and output are -- image inputs are found automatically).
Add the models it needs to `setup.sh`.
