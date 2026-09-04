"""Central configuration for the history simulator -- every tunable knob
lives in config.yaml (next to this file) so it can be adjusted without
touching code; this module just loads it and computes the one thing a
static file can't know on its own: which chat-model tier actually fits the
machine this is running on (hardware.py).
"""

from pathlib import Path

import yaml

import hardware

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


CHAT_MODEL = _pick_tier(_CHAT_MODEL_TIERS, _AVAILABLE_GB)
CHAT_CONTEXT_TOKENS = _RAW["chat_context_tokens"]

# --- History generation ---------------------------------------------------
FIGURES_PER_ERA = _RAW["generation"]["figures_per_era"]
EVENTS_PER_FIGURE = _RAW["generation"]["events_per_figure"]
RANDOM_SEED = _RAW["generation"]["random_seed"]
MAX_YEAR = _RAW["generation"]["max_year"]

# --- LLM-fill (see grammar.py / events.py) --------------------------------
LLM_FILL_NAMES = _RAW["llm_fill"]["fill_names"]
LLM_FLOURISH_RATE = _RAW["llm_fill"]["flourish_rate"]

# --- Map generation (citymap.py) ------------------------------------------
CHAR_WIDTH = _RAW["map"]["char_width"]
CHAR_HEIGHT = _RAW["map"]["char_height"]
LAND_DENSITY = _RAW["map"]["land_density"]
WATER_DENSITY = _RAW["map"]["water_density"]
NOISE_SCALE = _RAW["map"]["noise_scale"]
NOISE_OCTAVES = _RAW["map"]["noise_octaves"]
NOISE_PERSISTENCE = _RAW["map"]["noise_persistence"]
FALLOFF_POWER = _RAW["map"]["falloff_power"]
SEA_LEVEL = _RAW["map"]["sea_level"]
SATELLITE_SEA_LEVEL = _RAW["map"]["satellite_sea_level"]
NEIGHBORHOOD_COLUMNS = _RAW["map"]["neighborhood_columns"]
