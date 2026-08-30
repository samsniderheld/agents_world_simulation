"""Central configuration and hyperparameters.

Values for recency decay, retrieval weights, and the reflection threshold are
taken directly from the reference implementation at
github.com/joonspk-research/generative_agents
(reverie/backend_server/persona/memory_structures/scratch.py), so behavior
matches the paper's "Generative Agents: Interactive Simulacra of Human
Behavior" (Park et al., 2023) as closely as a barebones rewrite reasonably can.
"""

import hardware

# --- Ollama connection -------------------------------------------------
OLLAMA_HOST = "http://localhost:11434"

# Any locally-pulled chat model works -- picked automatically below to fit
# the memory actually available on this machine (Apple unified memory, or
# the first NVIDIA GPU's VRAM), since a laptop, an RTX 5090, and an H100 all
# want a different size of model. Each entry must already be pulled
# (`ollama pull <name>`) on whichever machine hits that tier. Adjust the
# GB cutoffs/model names to taste, or just hardcode CHAT_MODEL below to
# skip auto-detection entirely.
_CHAT_MODEL_TIERS = [
    # (minimum GB required, model)
    (60, "gpt-oss:120b"),              # e.g. H100 80GB
    (24, "Qwen3.8-27B"),     # e.g. RTX 5090 32GB VRAM
    (0, "llama3.1:8b"),                # e.g. M5 Pro 24GB unified memory
]

# Detected once and reused for every auto-sized setting below, so a laptop,
# an RTX 5090, and an H100 each only pay for one hardware probe.
_AVAILABLE_GB = hardware.available_memory_gb()


def _pick_tier(tiers: list, available_gb: float):
    for min_gb, value in tiers:
        if available_gb >= min_gb:
            return value
    return tiers[-1][1]


CHAT_MODEL = _pick_tier(_CHAT_MODEL_TIERS, _AVAILABLE_GB)

# Ollama's embedding model used for the memory stream's relevance scoring.
EMBED_MODEL = "nomic-embed-text"

# Context window (tokens) requested per call. Ollama otherwise defaults to
# the model's max context (e.g. 131072 for some Qwen models), which
# allocates a KV cache sized for that no matter how short the prompt is --
# on a memory-constrained machine that alone can push the process into swap
# and turn a one-word reply into a multi-minute wait. Our prompts here are
# short, so a modest window is plenty on small hardware; scaled up on
# machines with room for it. Adjust the tiers to taste, or hardcode
# CHAT_CONTEXT_TOKENS to skip auto-detection.
_CHAT_CONTEXT_TIERS = [
    # (minimum GB required, context tokens)
    (60, 32768),   # e.g. H100 80GB
    (24, 8192),    # e.g. RTX 5090 32GB VRAM
    (0, 4096),     # e.g. M5 Pro 24GB unified memory
]

CHAT_CONTEXT_TOKENS = _pick_tier(_CHAT_CONTEXT_TIERS, _AVAILABLE_GB)

# How long to wait for a single Ollama response before giving up. Larger
# models (e.g. 27B on 24GB of unified memory) are noticeably slower per
# token than the smaller default, so this is generous on purpose.
REQUEST_TIMEOUT_SECONDS = 300

# Whether to let "thinking" models (Qwen3.x, DeepSeek-R1, etc.) generate
# their hidden chain-of-thought before answering. This codebase makes many
# small calls per tick -- notably one per memory.add() just to rate
# importance 1-10 -- and a thinking model burns tens of seconds of hidden
# reasoning on every single one of those, even trivial ones. False cuts a
# 27B model's importance-rating call from ~20-30s to under 1s with the same
# answer. Ollama ignores this flag harmlessly for non-thinking models.
ENABLE_THINKING = False

# --- Memory retrieval (retrieve.py in the reference repo) --------------
RECENCY_DECAY = 0.99
RECENCY_WEIGHT = 1.0
IMPORTANCE_WEIGHT = 1.0
RELEVANCE_WEIGHT = 1.0
RETRIEVAL_TOP_K = 8

# --- Reflection (reflect.py in the reference repo) ----------------------
# Reflection fires once the sum of importance scores of new observations
# since the last reflection crosses this threshold.
REFLECTION_IMPORTANCE_THRESHOLD = 150
REFLECTION_LOOKBACK = 30          # how many recent memories feed focal points
REFLECTION_NUM_FOCAL_POINTS = 3
REFLECTION_INSIGHTS_PER_FOCAL_POINT = 3

# --- Simulation clock -----------------------------------------------------
TICK_MINUTES = 30

# --- Post-run treatment (treatment.py) ----------------------------------
# The treatment call reads the whole run's transcript in one shot, which is
# routinely far longer than the short per-tick prompts CHAT_CONTEXT_TOKENS is
# sized for, so it gets its own larger context window.
TREATMENT_CONTEXT_TOKENS = 8192
