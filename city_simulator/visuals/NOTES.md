# Local text-to-image research notes (MacBook Pro M5 Pro, 24GB)

Written before implementing `visuals/providers/local.py`, per instruction not
to guess model IDs/pipeline classes/settings from memory. Everything below
was verified directly against the installed `diffusers` source and model
cards/repos, not recalled from training data. Sources linked inline.

## Environment (as installed/verified on this machine)

- macOS 26.6.2, arm64 (M-series). `torch.backends.mps.is_available()` ->
  `True`, `is_built()` -> `True`.
- **Python 3.9.6 is the only interpreter available on this machine** (system
  `python3`, and the project's shared `.venv`). No 3.10/3.11/3.12/3.13
  found. This matters -- see the FLUX.2 blocker below.
- Installed into the shared `.venv`: `torch==2.8.0`, `torchvision==0.23.0`,
  `diffusers==0.36.0` (latest on PyPI as of this check -- confirmed via
  `pip index versions diffusers`), `transformers==4.57.6`,
  `accelerate==1.10.1`, `sdnq==0.1.3`.
- Confirmed present in `diffusers==0.36.0`'s pipeline tree:
  `pipelines/flux2/`, `pipelines/z_image/`, `pipelines/qwenimage/`.

## FLUX.2 [klein] 4B -- **not usable right now, on this machine**

Two independent, stacking blockers, both confirmed directly:

1. **The pipeline class the model card requires doesn't exist in any
   released diffusers version.** The model card for
   [`black-forest-labs/FLUX.2-klein-4B`](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
   says to use `Flux2KleinPipeline`, not the base `Flux2Pipeline`. That
   class lives at `pipeline_flux2_klein.py` on diffusers'
   [`main` branch only](https://github.com/huggingface/diffusers/blob/main/src/diffusers/pipelines/flux2/pipeline_flux2_klein.py)
   -- confirmed absent from the installed 0.36.0 (`grep` across the
   installed package tree finds nothing; PyPI has no newer release). A
   [related diffusers issue](https://github.com/huggingface/diffusers/issues/13087)
   ("cannot import name 'Flux2KleinPipeline' from 'diffusers'") confirms
   other users hit exactly this gap. Using it would require
   `pip install git+https://github.com/huggingface/diffusers.git`
   (unreleased, unpinned, moving target).
2. **Even the base `Flux2Pipeline` fails to import on Python 3.9,
   independent of (1).** `diffusers/pipelines/flux2/pipeline_flux2.py`
   uses bare PEP 604 union syntax (`List[PIL.Image.Image] | List[List[...]]`)
   as a live type annotation, with no `from __future__ import annotations`
   guarding it. That syntax requires Python 3.10+. Reproduced directly:
   ```
   >>> from diffusers import Flux2Pipeline
   TypeError: unsupported operand type(s) for |: '_GenericAlias' and '_GenericAlias'
   ```
   Since this machine's only available Python is 3.9.6, this blocks
   *any* FLUX.2 variant (dev or klein), not just klein specifically, and
   would block it even if (1) were solved by installing from git main --
   the git-main file most likely has the same annotation style.

**Bottom line:** FLUX.2 [klein] needs both a newer Python (3.10+, via a new
interpreter + venv) *and* an unreleased diffusers install to even attempt.
Not implementing it now rather than stubbing it out silently, per
instruction. If you install Python 3.10+ and want to revisit this, re-check
(1) and (2) against diffusers' then-current `main` before assuming it works.

Confirmed working, for reference: `black-forest-labs/FLUX.2-klein-4B` itself
is real (Apache 2.0, 4-step distilled, `num_inference_steps=4`,
`guidance_scale=1.0`, 1024x1024, ~13GB card-stated VRAM) -- it's the
tooling, not the model, that's blocked.

## Z-Image Turbo -- confirmed working, recommended default

- Repo: [`Tongyi-MAI/Z-Image-Turbo`](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo).
- Pipeline: `ZImagePipeline` (and `ZImageImg2ImgPipeline`) -- both import
  cleanly on this machine's Python 3.9 + diffusers 0.36.0. Verified
  directly (`from diffusers import ZImagePipeline` succeeds).
- 6B single-stream DiT transformer (`ZImageTransformer2DModel`).
- Text encoder: bundled in the repo's `text_encoder/` subfolder, config
  confirms `model_type: qwen3`, `Qwen3ForCausalLM`, hidden_size=2560,
  36 layers -- this is a Qwen3-4B-sized encoder (~4B params), *not* a
  small component; at bf16 that's ~8GB on its own during the encode step.
  Tokenizer: `Qwen2Tokenizer`.
- VAE: `AutoencoderKL`.
- Recommended settings per the model card: `num_inference_steps=9`
  (documented as "8 DiT forwards"), `guidance_scale=0.0` (guidance
  disabled for the Turbo variant), 1024x1024 default.
- Model card states it "fits comfortably within 16G VRAM consumer
  devices" -- the best fit of the three for this machine's ~16-17GB
  usable budget, especially with the encode-then-free-the-encoder
  sequencing already planned.
- diffusers' own `model_index.json` for this repo declares
  `"diffusers": "0.36.0.dev0"` -- i.e. this model was validated against
  essentially the same diffusers version installed here.
- **API shape, verified directly (not assumed):** `ZImagePipeline` has
  `enable_attention_slicing()` and `enable_model_cpu_offload()`, but
  *not* `enable_vae_slicing()` / `enable_vae_tiling()` -- those live on
  the VAE component itself for this pipeline class:
  `pipe.vae.enable_slicing()` / `pipe.vae.enable_tiling()`
  (`AutoencoderKL` has both). Calling the pipeline-level convenience
  methods that some other diffusers pipelines expose would raise
  `AttributeError` here.
- `enable_model_cpu_offload()` auto-detects the accelerator via
  `diffusers.utils.torch_utils.get_device()`, which explicitly checks
  `torch.backends.mps.is_available()` and returns `"mps"` -- confirmed in
  the installed source. No need to pass `device="mps"` explicitly, though
  doing so is harmless and more explicit.

## Qwen-Image -- the 7B "Qwen-Image-2.0" variant does not exist; flagging rather than guessing

- The user's brief asked for "the smaller 7B (Qwen-Image-2.0) variant... with
  the 20B available as an opt-in." **I could not verify a real,
  official 7B Qwen-Image-2.0 repo.** A web search surfaces an
  unofficial-looking blog (`qwenimages.com`, not a Qwen/Alibaba domain)
  and an arXiv paper page describing a "Qwen-Image-2.0, 7B" model, but
  checking the **actual Qwen organization page on Hugging Face**
  (https://huggingface.co/Qwen) turns up only:
  `Qwen/Qwen-Image`, `Qwen/Qwen-Image-2512`, `Qwen/Qwen-Image-Edit`,
  `Qwen/Qwen-Image-Edit-2511`, `Qwen/Qwen-Image-Edit-2509` -- no
  "Qwen-Image-2.0" or 7B general-purpose text-to-image repo among them.
  I'm not implementing a made-up repo ID; flagging this per instruction
  instead of stubbing it out silently.
- What's real: [`Qwen/Qwen-Image`](https://huggingface.co/Qwen/Qwen-Image)
  and its dated update [`Qwen/Qwen-Image-2512`](https://huggingface.co/Qwen/Qwen-Image-2512)
  are both **20B** parameter transformers (`QwenImageTransformer2DModel`).
  Pipeline: `QwenImagePipeline` -- imports cleanly on this machine's
  Python 3.9 + diffusers 0.36.0 (verified directly).
- Text encoder, per the pipeline class's own docstring in the installed
  diffusers source: `Qwen2.5-VL-7B-Instruct` -- a 7B vision-language
  model used as the *encoder*, separate from the 20B transformer. (This
  is likely the source of the "7B" in the brief -- the text encoder is
  7B, not the image model itself.)
- Recommended settings (from the `Qwen-Image-2512` card):
  `num_inference_steps=50`, `true_cfg_scale=4.0` (note: `true_cfg_scale`,
  not `guidance_scale` -- different kwarg name in this pipeline),
  resolutions like 1328x1328 (1:1) or 1664x928 (16:9).
- **Memory reality check:** 20B params at bf16 is ~40GB for the
  transformer alone -- already far past this machine's ~15GB ceiling,
  before the 7B text encoder or VAE. Even int8 SDNQ quantization
  (~1 byte/param) is ~20GB for the transformer alone, still over budget.
  Only an aggressive quantization (int4-ish, ~10GB for the transformer)
  has a chance of fitting under ~15GB total, and I have no verified
  report of this specific model at int4 on MPS -- real quality risk, and
  not something to promise works well. Implementing this as a genuine
  opt-in, off-by-default path with a loud warning, exactly as the brief
  asked for -- not recommending it as a first thing to try on this
  hardware.

## Quantization backends

- **bitsandbytes**: no MPS/Metal backend exists -- it only ships CUDA
  (and a CPU-only fallback on some platforms). Not usable here at all;
  not installing it.
- **SDNQ**: verified real and installed (`pip install sdnq`, got
  `sdnq==0.1.3`). Confirmed via direct inspection of the installed
  package:
  - Public API includes `SDNQConfig`, `sdnq_post_load_quant()`,
    `apply_sdnq_to_module()`, `load_sdnq_model()` / `save_sdnq_model()`.
  - **Diffusers' *native* `quantization_config=` integration needs
    `diffusers>=0.40.0`** (we have 0.36.0) -- but SDNQ also has a
    **standalone path that works with any diffusers version**:
    `sdnq_post_load_quant(model, weights_dtype="int8", ...)` quantizes an
    already-`from_pretrained()`-loaded module in place. This is the path
    to use here.
  - Exact confirmed signature (via `inspect.signature`):
    ```python
    sdnq_post_load_quant(
        model: torch.nn.Module, weights_dtype: str = "int8",
        quantized_matmul_dtype: str = None, torch_dtype: torch.dtype = None,
        group_size: int = 0, svd_rank: int = 32, svd_steps: int = 8,
        dynamic_loss_threshold: float = 0.01, use_svd: bool = False,
        quant_conv: bool = False, use_quantized_matmul: bool = False,
        use_quantized_matmul_conv: bool = False, use_dynamic_quantization: bool = False,
        use_stochastic_rounding: bool = False, dequantize_fp32: bool = False,
        non_blocking: bool = False, add_skip_keys: bool = True,
        modules_to_not_convert: List[str] = None, modules_dtype_dict: Dict[str, List[str]] = None,
        quantization_device: Optional[torch.device] = None, return_device: Optional[torch.device] = None,
    )
    ```
  - Confirmed `weights_dtype` values supported (from `sdnq/common.py`'s
    dtype table): `int8` down through `int7`...`int2`, `uint4`, plus
    float variants -- the "int8 down to low-bit" claim in the brief is
    accurate.
  - MPS: package printed `"SDNQ: Triton is not available. Falling back
    to PyTorch Eager mode."` on import here -- consistent with the
    documented MPS support path (PyTorch eager, no Triton on Mac).
    `quantized_matmul` fused kernels (`use_quantized_matmul=True`) are a
    CUDA/Triton-oriented optimization; leaving that off on MPS (the
    default is already `False`) rather than assuming it works.

## Decisions this leads to

1. Ship `local.py` supporting **only Z-Image Turbo**, SDNQ-quantized,
   behind the existing `Provider` interface. Neither of the other two
   requested models made the cut -- see #2 and #3.
2. **Do not** implement FLUX.2 [klein] yet -- documented above as blocked
   on two independent fronts, not stubbed out silently. Revisit if/when
   Python 3.10+ is available and diffusers ships `Flux2KleinPipeline` in
   a release.
3. **Do not** invent a "Qwen-Image-2.0 7B" repo ID -- it isn't real as far
   as I can verify, and the real alternative (`Qwen/Qwen-Image`, 20B) was
   never wired up either. If a real small variant is released later, add
   it then, from its actual model card.
