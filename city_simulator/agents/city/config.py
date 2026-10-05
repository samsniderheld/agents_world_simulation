"""CITY-mode tunables. SCENE mode reads agents/config.py and nothing here."""

import os

# --- The run's defaults --------------------------------------------------------
DEFAULT_SEED = 1959
DEFAULT_TICKS = 16

# --- Gateway (agents/gateway.py) ----------------------------------------------
REQUEST_TIMEOUT_SECONDS = 180      # one generation, including queueing on the server
MAX_RETRIES = 3                    # after the first attempt
BACKOFF_BASE_SECONDS = 0.5         # doubled per retry, times a random 0.5-1.5 jitter
BACKOFF_CAP_SECONDS = 20
EMBED_BATCH_SIZE = 64              # texts per /api/embed request
EMBED_MAX_CONCURRENCY = 4          # embed requests in flight
EMBED_MODEL = "nomic-embed-text"

# Where each tier's server is when the tier's provider is "openai"; both
# default to the SCENE-side OPENAI_COMPAT_BASE_URL.
HERO_BASE_URL = os.environ.get("CITY_HERO_BASE_URL")
BACKGROUND_BASE_URL = os.environ.get("CITY_BACKGROUND_BASE_URL")

# --- Output budgets (max tokens) per kind of call --------------------------------
TOKENS_PLAN = 300
TOKENS_DECOMPOSE = 300
TOKENS_SCHEDULE = 600
TOKENS_REACT = 60
TOKENS_LINE = 80
TOKENS_IMPORTANCE = 120
TOKENS_FOCAL = 150
TOKENS_INSIGHT = 250
TOKENS_BIO = 350
TOKENS_NARRATE = 200            # dice & DM: one check's narration (agents/dm/city.py)

# --- Encounters -------------------------------------------------------------------
MAX_ENCOUNTERS_PER_PLACE = 3       # per tick
MAX_DIALOGUE_TURNS = 6
END_MARKER = "[END]"

# --- Background tier ------------------------------------------------------------
BACKGROUND_MEMORY_SIZE = 40        # ring buffer entries per background agent
PROMOTE_AFTER_HERO_INTERACTIONS = 3
# Whether background agents' daily schedules come from the LLM (one call per
# agent per simulated day); False = occupation templates only, no LLM at all.
BACKGROUND_LLM_SCHEDULES = True

# --- Recording (agents/city/recorder.py) ----------------------------------------
EVENT_BUFFER_SIZE = 20000          # live ring buffer; hero events are also kept in full for persistence
