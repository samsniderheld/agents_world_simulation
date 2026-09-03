"""Central configuration for the history simulator."""

import hardware

# --- Ollama connection -------------------------------------------------
OLLAMA_HOST = "http://localhost:11434"

# Any locally-pulled chat model works -- picked automatically below to fit
# the memory actually available on this machine (Apple unified memory, or
# the first NVIDIA GPU's VRAM). Each entry must already be pulled
# (`ollama pull <name>`) on whichever machine hits that tier. Adjust the
# GB cutoffs/model names to taste, or just hardcode CHAT_MODEL below to
# skip auto-detection entirely.
_CHAT_MODEL_TIERS = [
    # (minimum GB required, model)
    (60, "gpt-oss:120b"),    # e.g. H100 80GB
    (32, "qwen2.5:14b"),     # e.g. RTX 5090 32GB VRAM
    (0, "llama3.1:8b"),      # e.g. M5 Pro 24GB unified memory
]

_AVAILABLE_GB = hardware.available_memory_gb()


def _pick_tier(tiers: list, available_gb: float):
    for min_gb, value in tiers:
        if available_gb >= min_gb:
            return value
    return tiers[-1][1]


CHAT_MODEL = _pick_tier(_CHAT_MODEL_TIERS, _AVAILABLE_GB)

# This project has no memory stream, so prompts are always a handful of
# sentences (name a proper noun, embellish one sentence) -- a small fixed
# context window is plenty regardless of hardware.
CHAT_CONTEXT_TOKENS = 2048

REQUEST_TIMEOUT_SECONDS = 120

# See agents/agent_simulator/config.py for why this matters: thinking
# models burn many seconds of hidden chain-of-thought on trivial fills
# (a place name, one embellished sentence) unless this is off.
ENABLE_THINKING = False

# --- History generation ---------------------------------------------------
FIGURES_PER_ERA = 4          # how many central figures each era spawns
EVENTS_PER_FIGURE = 10        # roughly how many life events drive each figure's arc
RANDOM_SEED = None            # set an int for a reproducible run

# Hard ceiling: a figure born late in the final era, running a full life-event
# chain unclamped, would otherwise drift well past the requested "up until
# the 1950s" scope. generate.py stops advancing a figure's story once it
# hits this year, rather than clamping every event to the era's own end
# year (which just piles up repeated-year events instead of stopping).
MAX_YEAR = 1959

# --- LLM-fill (see grammar.py / events.py) --------------------------------
# The grammar is fully procedural on its own; these just decide when the
# local LLM gets consulted to fill a blank instead of a static word list.
# Both degrade gracefully to pure-grammar output if Ollama is unreachable.
LLM_FILL_NAMES = True             # ask the LLM for proper nouns (place/ship/gang names)
LLM_FLOURISH_RATE = 0.35          # fraction of "notable" events that get a prose flourish pass
