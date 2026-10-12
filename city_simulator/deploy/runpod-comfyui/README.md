# ComfyUI on RunPod pods (images and video for the app)

Runs ComfyUI on RunPod GPU pods as an API the app calls
(`visuals/providers/comfyui.py`) -- one pod for images, one for video (or
one pod for both, if it has room):

| | workflow | models |
|---|---|---|
| **image** pod | Qwen-Image 2.1 image edit (`visuals/data/comfyui/qwen_image_2_1_edit.json`) | ~25 GB |
| **video** pod | MiniMax H3 image-to-video, with sound (`visuals/data/comfyui/minimax_h3_i2v.json`) | ~42 GB |

Once started they stay up -- no per-request cold start.

## The quick way: pods.py, from your Mac

`pods.py` creates and deletes the pods for you through RunPod's API:

```bash
python deploy/runpod-comfyui/pods.py up           # both pods (they boot at the same time)
python deploy/runpod-comfyui/pods.py up image     # or just one: create (or reuse) the image pod, ready to use
python deploy/runpod-comfyui/pods.py up video
python deploy/runpod-comfyui/pods.py status       # pods, $/hr, URLs, is ComfyUI up
python deploy/runpod-comfyui/pods.py down all     # delete both pods (stops GPU billing)
```

It needs `RUNPOD_API_KEY` in `city_simulator/.env` (RunPod console ->
Settings -> API Keys) -- your own key, in the file: on a RunPod pod the
environment already has a `RUNPOD_API_KEY` (a restricted per-pod key that
can't manage pods), so `pods.py` uses the one in `.env` first. GPUs, data
center and sizes are in `pods.yaml`.

Running it **on a RunPod pod** (e.g. the one running the app)? Give it an
SSH key that survives restarts, once:
`ssh-keygen -t ed25519 -f /workspace/.ssh/id_ed25519 -N ''`.

- **Nothing is lost on `down`.** Each kind has a RunPod network volume
  (`city-sim-comfyui-image` / `-video`) mounted at `/workspace`, holding
  ComfyUI and its models. `down` deletes only the pod; the next `up` attaches
  the same volume, so it's ready in minutes. Between runs you pay only the
  volume's storage. `down image --volume` deletes the volume too (it asks
  first; `--yes` skips that).
- **The first `up` of a kind sets the volume up.** RunPod's ComfyUI template
  copies ComfyUI onto the volume on first boot; `up` then runs `setup.sh` on
  the pod over SSH (your `~/.ssh/*.pub` key is given to the pod) to download
  the models and, if the template's ComfyUI is too old for the workflow's
  nodes, update it and restart the pod. Expect 15-30 minutes the first time
  (25-42 GB of models); later `up`s take a few minutes. With no SSH key, it
  tells you the one command to run in the pod's web terminal.
- **The app follows along.** When the pod is ready, `up` makes its URL the
  app's default ComfyUI server for that kind -- right away if the app is
  running, else when it next starts. No `.env` editing.
- **Data center:** a pod has to be in its volume's data center, and new
  volumes go to `datacenter` in `pods.yaml`. If `up` can't get any of the
  listed GPUs there, try again later or widen the GPU list. To move a kind to
  another data center, `down <kind> --volume`, change `datacenter`, and `up`.

**On the app's own pod, `deploy/runpod/start.sh` and `stop.sh` do this for
you:** `start.sh` runs `pods.py up` in the background after starting the app
(log: `/workspace/logs/comfyui-pods.log`; `COMFYUI_PODS=image|video|0` to
limit it), and `stop.sh` deletes the pods (`stop.sh pods` for just that).

The rest of this page is the manual way, and what `pods.py` does under the hood.

## 1. The pod

- **GPU:** image pod: 48 GB recommended (L40S, RTX 6000 Ada, A6000, A100);
  ~25 GB of weights, so a 24 GB card may work, slower. Video pod: 80 GB
  (A100/H100) or a Blackwell card (RTX PRO 6000, B200) -- ~42 GB of weights
  plus the video itself. The video workflow's text encoder is NVFP4, made for
  Blackwell GPUs; if it won't load on another GPU, see *Video on a
  non-Blackwell GPU* below.
- **Template:** RunPod's ComfyUI template is easiest (its ComfyUI, in
  `/workspace/runpod-slim/ComfyUI`, starts with the pod). Any PyTorch / Ubuntu
  image works too -- `setup.sh` then installs ComfyUI itself.
- **Volume:** 60 GB+ (image) / 80 GB+ (video) at `/workspace` -- ComfyUI and
  the models live there, so they survive pod restarts.
- **Expose HTTP Ports:** `8188`.

## 2. Models and a check

In the pod's terminal (Jupyter or SSH):

```bash
cd /workspace
git clone https://github.com/samsniderheld/agents_world_simulation.git   # once
cd agents_world_simulation && git checkout comfyui_pod
bash city_simulator/deploy/runpod-comfyui/setup.sh          # image pod
bash city_simulator/deploy/runpod-comfyui/setup.sh video    # or: video pod
bash city_simulator/deploy/runpod-comfyui/start.sh
```

`setup.sh` finds the pod's ComfyUI -- the one running on port 8188, else
one on the volume -- and puts that workflow's models in the folders that
ComfyUI reads them from (the same place its web UI's model downloads go;
models already there are skipped). Then it checks ComfyUI has every node the
workflow uses (Qwen-Image 2.1 needs ComfyUI 0.37.0+, MiniMax H3 0.39.0+), so
an older install gets a clear message to update it. Only on a pod with no
ComfyUI at all does it install one (v0.39.2 at `/workspace/ComfyUI`;
`COMFYUI_VERSION=master` for the newest, `COMFYUI_DIR` to pick a folder).

`start.sh` makes sure ComfyUI is up and prints the URL to use; it only
starts a ComfyUI that `setup.sh` installed (a template's runs on its own).
`stop.sh` stops that one.

## 3. Point the app at it

In `city_simulator/.env` on the machine running the app:

```
VISUALS_IMAGE_PROVIDER=comfyui
COMFYUI_IMAGE_URL=https://<image pod id>-8188.proxy.runpod.net
VISUALS_VIDEO_PROVIDER=comfyui
COMFYUI_VIDEO_URL=https://<video pod id>-8188.proxy.runpod.net
```

then restart the app. Those are the defaults: every Image and Video node
also has a provider picker (*default*, *fal.ai*, *ComfyUI*), so you can
switch per node. Music always uses fal.

**Video:** the Video node's source image is the first frame; its aspect
ratio and prompt go into the workflow, and clips are 5 s by default
(`default_duration` in `visuals/data/config.yaml`). MiniMax H3 writes the
soundtrack too, so a good prompt describes the sound as well as the motion.

**Size:** the Image node's aspect ratio and **1K / 2K** pickers set the
output: 1K is about 1 megapixel (16:9 = 1376 x 768), 2K about 4 (2720 x
1536) -- also when reference images are wired in (their pixel budget follows
the same setting).

**No password:** ComfyUI has no login, so anyone who has the pod's URL can
run jobs on it while it's up. Stop the pod when you're done (that also stops
the billing).

## Video on a non-Blackwell GPU

The video workflow's text encoder (`qwen3vl_32b_minimax_h3_nvfp4_awq`) is in
NVFP4, a format made for NVIDIA's Blackwell GPUs. If the video pod's GPU
can't load it (the job fails at the CLIP loader), use the int8 one instead:

1. on the pod: `MINIMAX_TEXT_ENCODER=int8 bash city_simulator/deploy/runpod-comfyui/setup.sh video` (27 GB)
2. in `visuals/data/config.yaml`, under `video_workflow`, uncomment the `set:`
   lines that point node `105:13` at `qwen3vl_32b_minimax_h3_int8_convrot.safetensors`.

## Models

| folder | file | size |
|---|---|---|
| `models/diffusion_models` | `qwen_image_2.1_int8_convrot.safetensors` | 6.8 GB |
| `models/text_encoders` | `qwen3vl_8b_int8_convrot.safetensors` | 8.7 GB |
| `models/text_encoders` | `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | 8.8 GB (prompt enhancer) |
| `models/vae` | `qwen_image_2.1_vae_bf16.safetensors` | 0.6 GB |

From [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1).
The video pod's, from [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3):

| folder | file | size |
|---|---|---|
| `models/diffusion_models` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 21.0 GB |
| `models/text_encoders` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` (or the int8 one, 27.1 GB) | 15.7 GB |
| `models/vae` | `minimax_h3_video_vae_fp16.safetensors` | 5.2 GB |
| `models/vae` | `minimax_h3_audio_vae_fp32.safetensors` | 0.6 GB |

## Another workflow

Export it from ComfyUI with *Export (API)* into `visuals/data/comfyui/`, and
describe it in `visuals/data/config.yaml`'s `comfyui` section (where its
prompt, seed, size and output are -- image inputs are found automatically).
Add the models it needs to `setup.sh`.
