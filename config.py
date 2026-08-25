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
CHAT_MODEL = "llama3.1:8b"

# Ollama's embedding model used for the memory stream's relevance scoring.
EMBED_MODEL = "nomic-embed-text"

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
