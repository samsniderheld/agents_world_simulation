"""Central configuration for the history simulator -- every tunable knob
lives in config.yaml (next to this file) so it can be adjusted without
touching code; this module just loads it and computes the one thing a
static file can't know on its own: which chat-model tier actually fits the
machine this is running on (hardware.py).
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

import hardware

load_dotenv(Path(__file__).parent.parent / ".env")

_CONFIG_PATH = Path(__file__).parent / "data" / "config.yaml"

with open(_CONFIG_PATH) as _f:
    _RAW = yaml.safe_load(_f)

# --- Ollama connection -------------------------------------------------
OLLAMA_HOST = _RAW["ollama"]["host"]
REQUEST_TIMEOUT_SECONDS = _RAW["ollama"]["request_timeout_seconds"]
ENABLE_THINKING = _RAW["ollama"]["enable_thinking"]

_CHAT_MODEL_TIERS = [(tier["min_gb"], tier["model"]) for tier in _RAW["chat_model_tiers"]]

# Detected once and reused -- see hardware.py's docstring.
_AVAILABLE_GB = hardware.available_memory_gb()


def _pick_tier(tiers: list, available_gb: float):
    for min_gb, value in tiers:
        if available_gb >= min_gb:
            return value
    return tiers[-1][1]


# OLLAMA_CHAT_MODEL (env or .env) skips the auto-pick, same as agents/config.py.
CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL") or _pick_tier(_CHAT_MODEL_TIERS, _AVAILABLE_GB)
CHAT_CONTEXT_TOKENS = _RAW["chat_context_tokens"]

# --- History generation ---------------------------------------------------
FIGURES_PER_ERA = _RAW["generation"]["figures_per_era"]
EVENTS_PER_FIGURE = _RAW["generation"]["events_per_figure"]
RANDOM_SEED = _RAW["generation"]["random_seed"]
# (The final year of a history is the theme's world.present_year -- theme.py.)

# --- LLM-fill (see grammar.py / events.py) --------------------------------
LLM_FILL_NAMES = _RAW["llm_fill"]["fill_names"]
LLM_FLOURISH_RATE = _RAW["llm_fill"]["flourish_rate"]

# --- End-of-run history summary (summary.py) -------------------------------
SUMMARY_CONTEXT_TOKENS = _RAW["summary"]["context_tokens"]
SUMMARY_REQUEST_TIMEOUT_SECONDS = _RAW["summary"]["timeout_seconds"]
