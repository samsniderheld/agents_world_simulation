"""Local text-to-image generation via Hugging Face Diffusers on PyTorch's
MPS backend (Apple Silicon). See visuals/NOTES.md for the research this is
built on: verified pipeline classes, repo ids, and recommended settings,
and why FLUX.2 [klein] and Qwen-Image are *not* wired up here (the former
needs a pipeline class only on diffusers' unreleased main branch plus
Python 3.10+; the latter's requested 7B "Qwen-Image-2.0" variant doesn't
appear to be a real released model) -- confirmed, not guessed, and not
stubbed out silently.

PYTORCH_ENABLE_MPS_FALLBACK must be set before torch is imported anywhere
in the process, so it's set here at import time, before the `import torch`
line below. This means local.py must stay lazily imported (see
providers/__init__.py's get_provider(), which only imports this module
when config.yaml's `provider` is actually "local") rather than imported
eagerly at application startup, since by then some other module may
already have imported torch.
"""

import os

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import random
import threading

import torch
from diffusers import ZImagePipeline

from .. import config
from .. import storage
from .base import Provider

_MAX_UNTILED_SIDE = 1024  # switch the VAE from slicing to tiling above this


class LocalProvider(Provider):
    """Loads the pipeline once (lazily, on first use) and reuses it across
    calls -- reloading a multi-billion-parameter model per request would
    dominate latency far more than keeping it resident does."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pipe = None

    def _require_mps(self):
        if not torch.backends.mps.is_available():
            raise RuntimeError(
                "PyTorch's MPS backend is not available on this machine -- "
                "the local provider only supports Apple Silicon via MPS."
            )

    def _load(self):
        with self._lock:
            if self._pipe is not None:
                return self._pipe

            self._require_mps()
            pipe = ZImagePipeline.from_pretrained(config.LOCAL_MODEL_ID, torch_dtype=torch.bfloat16)

            if config.LOCAL_QUANTIZE:
                from sdnq import sdnq_post_load_quant
                sdnq_post_load_quant(pipe.transformer, weights_dtype=config.LOCAL_QUANTIZE_DTYPE)
                sdnq_post_load_quant(pipe.text_encoder, weights_dtype=config.LOCAL_QUANTIZE_DTYPE)

            # No batching (unreliable on MPS -- callers loop one prompt at a
            # time instead) and no torch.compile (unstable for DiTs on MPS
            # as of this writing). Left here, commented, as the hook to
            # flip on later if/when that changes:
            # pipe.transformer = torch.compile(pipe.transformer, mode="reduce-overhead")

            pipe.enable_attention_slicing()
            # ZImagePipeline has no enable_vae_slicing()/enable_vae_tiling()
            # of its own (verified -- see NOTES.md) -- those live on the VAE
            # component directly.
            pipe.vae.enable_slicing()

            # Sequential text_encoder -> transformer -> vae offload (that
            # exact order is ZImagePipeline's own model_cpu_offload_seq):
            # only one component is "hot" on the accelerator at a time, so
            # the encode-then-denoise peaks never stack. diffusers
            # auto-detects "mps" as the accelerator here.
            pipe.enable_model_cpu_offload()

            self._warmup(pipe)
            self._pipe = pipe
            return pipe

    def _warmup(self, pipe):
        """A throwaway 1-step generation right after load, before any real
        request -- this is where MPS's shader/kernel compilation for this
        exact model shape happens, so it doesn't inflate the first real
        image's latency."""
        pipe(
            prompt="warmup", height=64, width=64, num_inference_steps=1,
            guidance_scale=0.0, generator=torch.Generator(device="mps").manual_seed(0),
        )

    def generate_image(self, prompt: str, image_paths: list = None, **options) -> dict:
        if image_paths:
            raise NotImplementedError(
                "the local provider only supports text-to-image right now (Z-Image Turbo) -- "
                "no local image-editing model is wired up yet, see visuals/NOTES.md"
            )

        pipe = self._load()

        height = int(options.get("height", 1024))
        width = int(options.get("width", 1024))
        if max(height, width) > _MAX_UNTILED_SIDE:
            pipe.vae.enable_tiling()
        else:
            pipe.vae.disable_tiling()

        seed = options.get("seed")
        if seed is None:
            seed = random.randint(0, 2**32 - 1)
        generator = torch.Generator(device="mps").manual_seed(seed)

        result = pipe(
            prompt=prompt,
            height=height, width=width,
            num_inference_steps=int(options.get("num_inference_steps", config.LOCAL_NUM_INFERENCE_STEPS)),
            guidance_scale=float(options.get("guidance_scale", config.LOCAL_GUIDANCE_SCALE)),
            generator=generator,
        )

        images = []
        for image in result.images:
            local_path = storage.save_pil_image(image)
            images.append({
                "local_path": str(local_path), "url": storage.relative_path(local_path),
                "width": image.width, "height": image.height, "content_type": "image/png",
            })
        return {"images": images, "description": "", "seed": seed}

    def generate_video(self, prompt: str, image_path: str, **options) -> dict:
        raise NotImplementedError(
            "the local provider does not support video generation -- only fal.ai does right now"
        )
