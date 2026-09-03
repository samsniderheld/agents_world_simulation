# city simulator

A single local app, in two connected halves, both running on-device via
[Ollama](https://ollama.com):

1. **History** — procedurally generates a ~330-year history (1624 Dutch
   colonization → the late 1950s) for a single NYC-inspired city: a catalog
   of historical places (taverns, markets, churches, shipyards, tenements,
   theaters) each with a full internally-consistent backstory, an ASCII map
   colored by neighborhood, and ten present-day residents grounded in that
   history.
2. **Agents** — a minimal implementation of the "Generative Agents"
   architecture (Park et al., 2023): agents with a memory stream, retrieval,
   reflection, planning, and reacting/dialogue. The ten residents generated
   by the History tab become the agent roster, restaged onto a few shared
   locations so they can actually meet and talk (see `simulation.py`'s
   `roster_from_history`); without a generated history, a fixed five-person
   noir cast is used instead.

Both are driven from one web UI (`index.html`) with a tab per half. A third
tab is reserved for later.

## Setup

1. Install Ollama, then start it with the helper script (idempotent -- safe
   to run even if it's already up):
   ```bash
   brew install ollama
   ./start_ollama.sh
   ```
   Stop it later with `./stop_ollama.sh`.
2. Pull a chat model and the embedding model (the agent side uses embeddings
   for memory retrieval; the history side doesn't). `agent_config.py` and
   `history_config.py` each auto-detect the machine's available memory
   (`hardware.py`) and pick a model sized to it -- pull whichever tier
   applies, adjusting `_CHAT_MODEL_TIERS` in either config to taste:
   ```bash
   ollama pull llama3.1:8b
   ollama pull nomic-embed-text
   ```
3. Install Python deps (Python 3.9+; there's a shared `.venv` one level up
   in this repo):
   ```bash
   python3 -m venv ../.venv && source ../.venv/bin/activate
   pip install -r requirements.txt
   ```
4. Run it:
   ```bash
   python3 server.py
   ```
   Opens a browser to the History tab. Generate a history there, switch to
   the Agents tab, and start a run -- its roster will already reflect
   whatever you just generated.

Everything also still works without Ollama running: the History tab's
"Skip Ollama" checkbox falls back to pure-grammar names/prose, and the
Agents tab will raise a clear error at the start of a run if the configured
model isn't pulled.

## How it works

```text
index.html (3 tabs)
  |
  |-- History tab --> POST /api/history/generate --> history_generate.run_history()
  |                     |                              |
  |                     |                              |-- generate()       schedule + resolve every
  |                     |                              |                     Figure's life events in true
  |                     |                              |                     chronological order (see
  |                     |                              |                     history_generate.py's docstring)
  |                     |                              |-- citymap.build_map()      ASCII map, braille
  |                     |                              |                             dot-density, colored
  |                     |                              |                             by era neighborhood
  |                     |                              `-- characters.generate_characters()  10 present-day
  |                     |                                                                     residents grounded
  |                     |                                                                     in real places/figures
  |                     v
  |                   GET /api/history/status (poll) --> GET /api/history/data (once done)
  |
  `-- Agents tab --> POST /api/agents/run --> simulation.run()
                        |                        |
                        |                        |-- simulation.build_agents()   roster_from_history() if a
                        |                        |                                history was generated this
                        |                        |                                session, else the hardcoded
                        |                        |                                noir AGENT_ROSTER
                        |                        `-- world.World.run()          tick loop: plan / decompose,
                        |                                                        perceive + react (+ dialogue),
                        |                                                        reflect -- see world.py's docstring
                        v
                      GET /api/agents/state (poll) + GET /api/agents/stream (SSE)  -->  live per-agent columns
```

`server.py` runs each half as its own background thread with its own
status, so generating a history and running agents are independent jobs
the frontend can drive separately.

## Architecture

| File(s) | Half | What it does |
|---|---|---|
| `server.py` | both | Unified local web server: serves `index.html`, runs history generation and agent runs each on a background thread, exposes `/api/history/*` and `/api/agents/*`. |
| `history_config.py` / `history_llm.py` | history | Config (era/place/LLM-fill tuning) and a thin Ollama chat wrapper, tuned for many short name/prose-fill calls. |
| `eras.py`, `entities.py`, `events.py`, `grammar.py`, `names.py` | history | The procedural-history engine itself -- modeled on Jason Grinblat's GDC talk on Caves of Qud's mythic-biography generator: entities as mutable-property bags, events resolved by reading current state (not simulated causality), text produced by a real replacement grammar (`grammar.py`). |
| `citymap.py` | history | The ASCII map: Perlin-noise-generated island + satellite landmasses, rendered as braille dot-density, each era's row-band a separately colored/named neighborhood. |
| `characters.py` | history | Ten present-day residents, each grounded in one real place's founder/domain/history. |
| `history_generate.py` | history | `run_history()` (called by the server) and a standalone CLI (`python3 history_generate.py --seed 42`) that does the same thing plus writes `history.json`/`map.txt`/`characters.json`. |
| `agent_config.py` / `agent_llm.py` | agents | Config (recency/reflection/retrieval tuning, from the reference implementation) and a thin Ollama chat+embeddings wrapper. |
| `agent.py`, `memory.py`, `planning.py`, `reflection.py`, `world.py` | agents | The generative-agents cognitive core -- memory stream + retrieval, reflection, planning, reacting/dialogue, and the tick-based simulation loop. See each file's docstring. |
| `simulation.py` | agents | `run()` (called by the server), the hardcoded noir `AGENT_ROSTER` fallback, and `roster_from_history()` -- restages a generated history's characters onto a few shared hub locations so they can meet and talk. |
| `treatment.py` | agents | One LLM call after a run finishes: a film-noir video-vignette treatment (cast, synopsis, storyboard) over the full transcript. |
| `recorder.py` / `display.py` / `textutil.py` | agents | Structured event log the frontend streams live (`recorder.py`), terminal color helpers for `--verbose` tracing (`display.py`), small text-parsing helpers (`textutil.py`). |
| `hardware.py` | both | Detects available memory (Apple unified memory or NVIDIA VRAM) so each config can size its chat model to the machine it's running on. |

## Extending

- The third tab in `index.html` is a placeholder (`data-tab-panel="soon"`) --
  wire up its own `/api/<name>/*` routes in `server.py` the same way the
  other two are namespaced.
- `simulation.roster_from_history()`'s hub-clustering (`_HUB_COUNT`, `_pick_hubs`)
  is the seam to change if you want a different way of staging generated
  characters for a live run -- e.g. more hubs, or grouping by neighborhood
  instead of raw history-richness.
- See `history_generate.py`'s and `world.py`'s "Deliberate simplifications"
  notes (in their docstrings / the git history of the original two
  projects) for known scope cuts worth revisiting.
