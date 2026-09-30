"""Best-effort detection of how much memory is available to run a local
model against, so config.py can size CHAT_MODEL to the machine it's running
on (Apple Silicon's unified memory, or an NVIDIA GPU's VRAM) instead of a
single hardcoded model that's wrong on every machine but one.
"""

import platform
import subprocess


def available_memory_gb() -> float:
    """Total unified memory on Apple Silicon, or the first NVIDIA GPU's
    total VRAM everywhere else. Returns 0.0 if neither can be detected,
    which config.py treats as "assume the smallest supported machine"."""
    if platform.system() == "Darwin":
        return _apple_unified_memory_gb()
    return _nvidia_vram_gb()


def _apple_unified_memory_gb() -> float:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return int(out.stdout.strip()) / (1024 ** 3)
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return 0.0


def _nvidia_vram_gb() -> float:
    """VRAM of the first GPU reported by nvidia-smi. Multi-GPU boxes are
    treated as having just that much memory, since Ollama doesn't split a
    single model's weights across devices by default."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        first_gpu_mib = int(out.stdout.strip().splitlines()[0])
        return first_gpu_mib / 1024
    except (subprocess.SubprocessError, ValueError, FileNotFoundError, IndexError):
        return 0.0


# --- CITY mode hardware profiles ------------------------------------------
# Used only by CITY mode (agents/city/, agents/gateway.py) and
# start_ollama.sh. SCENE mode keeps sizing its one model from
# agents/config.py's _CHAT_MODEL_TIERS, untouched by anything here.
#
# Each profile picks, for its class of machine: the backend, the model for
# each tier (HERO agents get full cognition; BACKGROUND agents only need
# short schedules and one-liners), how many requests to keep in flight, the
# context window, and how many agents a run may have in total. Every model
# name is only a default: the City Simulation node can override the
# provider/model per tier, and CITY_HERO_BASE_URL / CITY_BACKGROUND_BASE_URL
# point the tiers at different servers (one vLLM server usually serves one
# model). A tier whose model isn't available falls back to the hero model.

import os

CITY_PROFILES = {
    # Apple Silicon, one local Ollama. Both tiers stay loaded at once
    # (OLLAMA_MAX_LOADED_MODELS=2, see start_ollama.sh).
    "mac": {
        "label": "Mac (Ollama, up to 64 GB unified memory)",
        "provider": "ollama",
        "hero_model": "llama3.1:8b",
        "background_model": "llama3.2:3b",
        "max_concurrency": 4,          # raised to 8 on 48 GB+ (see city_profile)
        "context_tokens": 4096,
        "population_cap": 200,
        "hero_cap": 30,
        # Background schedules written by the model each sim-day; the rest
        # use occupation templates (a 3B model on a laptop does ~5/min).
        "llm_schedule_cap": 40,
        "schema_mode": "native",
    },
    # One RTX 5090 (32 GB) running vLLM: a mixture-of-experts hero model
    # (fast per token for its size) and a small background model.
    "rtx5090": {
        "label": "RTX 5090 (vLLM)",
        "provider": "openai",
        "hero_model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "background_model": "Qwen/Qwen3-4B-Instruct-2507",
        "max_concurrency": 128,
        "context_tokens": 8192,
        "population_cap": 1000,
        "hero_cap": 200,
        # Background schedules written by the model each sim-day; the rest
        # use occupation templates (a 3B model on a laptop does ~5/min).
        "llm_schedule_cap": 1000,
        "schema_mode": "response_format",
    },
    # One H100 80 GB running vLLM: a larger MoE hero (fits one card).
    "h100": {
        "label": "H100 80 GB (vLLM)",
        "provider": "openai",
        "hero_model": "openai/gpt-oss-120b",
        "background_model": "Qwen/Qwen3-8B",
        "max_concurrency": 256,
        "context_tokens": 16384,
        "population_cap": 2000,
        "hero_cap": 200,
        # Background schedules written by the model each sim-day; the rest
        # use occupation templates (a 3B model on a laptop does ~5/min).
        "llm_schedule_cap": 2000,
        "schema_mode": "response_format",
    },
}


def detect_city_profile() -> str:
    """The profile that fits this machine: a Mac is "mac"; an NVIDIA card
    with 70 GB+ is "h100", 24 GB+ is "rtx5090"; anything else is treated
    like the Mac profile (small local Ollama). CITY_PROFILE overrides."""
    forced = os.environ.get("CITY_PROFILE")
    if forced in CITY_PROFILES:
        return forced
    if platform.system() == "Darwin":
        return "mac"
    vram = _nvidia_vram_gb()
    if vram >= 70:
        return "h100"
    if vram >= 24:
        return "rtx5090"
    return "mac"


def city_profile(name: str = "auto") -> dict:
    """A copy of one profile ("auto" = detect_city_profile()), with "name"
    and "ollama_num_parallel" (what start_ollama.sh gives Ollama) set."""
    if name not in CITY_PROFILES:
        name = detect_city_profile()
    profile = dict(CITY_PROFILES[name], name=name)
    if name == "mac" and available_memory_gb() >= 48:
        profile["max_concurrency"] = 8
    profile["ollama_num_parallel"] = profile["max_concurrency"] if profile["provider"] == "ollama" else 4
    return profile
