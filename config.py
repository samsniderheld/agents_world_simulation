"""Central configuration and hyperparameters.

Values for recency decay, retrieval weights, and the reflection threshold are
taken directly from the reference implementation at
github.com/joonspk-research/generative_agents
(reverie/backend_server/persona/memory_structures/scratch.py), so behavior
matches the paper's "Generative Agents: Interactive Simulacra of Human
Behavior" (Park et al., 2023) as closely as a barebones rewrite reasonably can.
"""

# --- Ollama connection -------------------------------------------------
OLLAMA_HOST = "http://localhost:11434"

# Any locally-pulled chat model works. Pick one that fits your RAM headroom;
# an M5 Pro with 24GB+ unified memory comfortably runs 8B-14B q4/q5 models.
# CHAT_MODEL = "batiai/qwen3.6-27b:q4"
CHAT_MODEL = "llama3.1:8b"

# Ollama's embedding model used for the memory stream's relevance scoring.
EMBED_MODEL = "nomic-embed-text"

# Context window (tokens) requested per call. Ollama otherwise defaults to
# the model's max context (e.g. 131072 for some Qwen models), which
# allocates a KV cache sized for that no matter how short the prompt is --
# on a memory-constrained machine that alone can push the process into swap
# and turn a one-word reply into a multi-minute wait. Our prompts here are
# short, so a modest window is plenty; raise it if you see truncated output.
CHAT_CONTEXT_TOKENS = 4096

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
