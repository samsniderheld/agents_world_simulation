# barebones generative agents

A minimal, local-only implementation of the architecture from
["Generative Agents: Interactive Simulacra of Human Behavior"](https://arxiv.org/abs/2304.03442)
(Park et al., 2023) and the reference implementation at
[joonspk-research/generative_agents](https://github.com/joonspk-research/generative_agents),
built to run entirely on-device (e.g. an Apple M5 Pro) via [Ollama](https://ollama.com).

No WebGL front end and no cloud API calls. The cognitive core (memory stream,
retrieval, reflection, planning, reacting/dialogue) follows the paper; the
world agents move through is a departure from it — a small procedurally
generated ASCII city, Dwarf-Fortress-inspired, with real (x, y, z) positions
and multi-floor buildings agents pathfind through, printed as ASCII snapshots
rather than rendered live (see "The world" below).

## How it works

Each call to `World.step()` (see `world.py`) runs one simulated tick in four
phases, across all agents:

```text
World.step()  --  one simulation tick
  |
  v
PHASE 1: Plan & Act  (every agent)
  |
  |-- Plan left for today?
  |       |
  |       |-- no  --> planning.generate_daily_plan()
  |       |             (5-8 broad-stroke items)
  |       |               |
  |       `-- yes ------- v
  |             planning.decompose()
  |             (next broad step -> a few small actions)
  |               |
  |               v
  |             set current_action;
  |             add it as an observation in own memory
  |               |
  |               v
  |             does current_action mention a known building by name?
  |               |
  |               |-- yes --> set dest = city.entry_point(building)
  |               `-- no  --> keep whatever dest it already had
  v
PHASE 2: Move  (every agent)
  |
  |-- has a dest?
  |       |
  |       |-- no  --> stay put
  |       `-- yes --> pathfinding.find_path(city, pos, dest)
  |                     (recomputed only if stale)
  |                     advance up to MOVE_SPEED tiles along it
  v
PHASE 3: Perceive & React  (every pair within NEARBY_RADIUS tiles,
  |                          same z-level)
  |
  |-- perceive: add the other agent's action as an observation
  |               |
  |               v
  |-- agent.react()
  |     retrieve relevant memories, ask the LLM:
  |     continue plan, or react?
  |               |
  |               v
  |-- reacted with something dialogue-like?
  |       |
  |       |-- no  --> skip to Phase 4
  |       `-- yes --> world._run_conversation()
  |                     alternating converse_turn(), up to 6 lines
  |                       |
  |                       v
  |                     store transcript as a 'chat' memory
  |                     in both agents
  v
PHASE 4: Reflect  (every agent)
  |
  |-- importance_since_reflection >= 150?
  |       |
  |       |-- no  --> skip
  |       `-- yes --> reflection.reflect()
  |                     focal points -> retrieve -> cited insights,
  |                     stored as 'reflection' memories
  v
tick += 1  ------------------------------->  back to World.step()
```

Everything an agent perceives, decides, plans, or reflects on is written into
its `MemoryStream` (`memory.py`) as a `MemoryNode`. Every LLM call that needs
context — reacting, planning, reflecting, talking — starts by calling
`memory.retrieve()`, which scores all nodes by a weighted sum of recency,
importance, and relevance and returns the top few. That retrieval loop is the
one piece of machinery every other module leans on:

```text
query text  (an observation, a focal point, or a plan step)
  |
  v
embed via Ollama (nomic-embed-text)  ------------------------+
                                                               |
MemoryStream.nodes                                            |
  |                                                            |
  |-- recency score     =  0.99 ^ rank, newest first           |
  |-- importance score  =  1-10, LLM-rated                     |
  `-- relevance score   =  cosine similarity to the embedding <+
  |
  v
weighted sum  (recency + importance + relevance, all weights = 1)
  |
  v
top-k nodes
  |
  v
fed back into the next LLM prompt
```

### The world

`city.py` procedurally lays out a small city as a 3D tile grid: a street
level (z=0) with a handful of buildings on it, each with its own floors
stacked above (z=1, z=2, ...). Every building gets a door linking the
street to floor 1, and a stairwell column linking each floor to the next —
see `city.generate_small_city()`. `pathfinding.py` runs breadth-first search
over that grid (ordinary 4-directional moves, plus the door/stairwell links)
to route an agent from its current tile to a destination. Agents advance a
few tiles along that route each tick (`world._advance()`), and "being near
someone" (for reactions/dialogue) means being within a few tiles on the same
floor, not matching a location string.

Run with `--map` to print an ASCII snapshot of every occupied floor after
each tick (`render.py`, kept as a standalone function so a future live/
curses viewer can call it too):

```text
-- z=1 -------------------------------------------
                                                  
                          #######                 
                          #....^#                 
                          #..OL.#                 
                          #.....#                 
                          #+#####                 
                                                  
legend: # wall  . floor/street  + door  ^ stairs  letters = agents
O=Oswald@(29, 4, 1), L=Lou@(30, 4, 1)
```

## Setup

1. Install Ollama, then start it with the helper script (idempotent -- safe
   to run even if it's already up; uses `brew services` if Ollama was
   installed via Homebrew, otherwise runs `ollama serve` in the background):
   ```bash
   brew install ollama
   ./start_ollama.sh
   ```
   Stop it later with `./stop_ollama.sh`.
2. Pull a chat model and the embedding model:
   ```bash
   ollama pull llama3.1:8b       # or qwen2.5:14b, mistral, etc.
   ollama pull nomic-embed-text
   ```
   Model sizing rule of thumb for an M5 Pro: an 8B model (q4/q5) is
   comfortable on 16GB+ of unified memory; a 14B model wants 24GB+. Bigger
   models make noticeably better planning/reflection judgments at the cost
   of tokens/sec.
3. Install Python deps (Python 3.9+):
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. Run it:
   ```bash
   python3 main.py --ticks 8
   python3 main.py --ticks 8 --map           # also print an ASCII map each tick
   python3 main.py --ticks 8 --tick_sleep 1  # pause between lines, easier to read live
   ```

To use different models without touching `config.py`:
```bash
python3 main.py --chat-model qwen2.5:14b --embed-model nomic-embed-text
```

## Architecture

| File | Paper concept | What it does |
|---|---|---|
| `memory.py` | Memory stream + retrieval | Stores every observation/reflection/plan as a `MemoryNode` (description, timestamp, LLM-rated importance 1-10, embedding). `retrieve()` scores nodes by `recency_w*recency + importance_w*importance + relevance_w*relevance`, normalizes each component to [0,1], and returns the top-k. |
| `reflection.py` | Reflection | Once the sum of new observations' importance crosses a threshold (150, same as the reference repo), the agent generates 2-3 high-level "focal point" questions from recent memories, retrieves relevant memories for each, and asks the LLM for insights with cited evidence — stored back into the memory stream as `reflection` nodes. |
| `planning.py` | Planning | Generates a 5-8 item broad-strokes daily plan from the agent's identity, then decomposes each broad step into a few finer actions as it's reached. |
| `agent.py` | Reacting + dialogue | `react()` retrieves relevant memories and asks the LLM whether to continue the current plan or do something else given a new observation. `converse_turn()` generates one line of dialogue at a time, grounded in retrieved memories about the other agent. |
| `world.py` | Simulation loop | A tick-based loop (default 30 sim-minutes/tick): agents advance their plan and position, perceive nearby agents, may react (including breaking into conversation), and are checked for reflection each tick. |
| `city.py` | — (not in the paper) | Procedurally generates the 3D tile city agents move through: street level plus multi-floor buildings, doors, and stairwells. See "The world" above. |
| `pathfinding.py` | — (not in the paper) | Breadth-first search over a `City`'s tile grid, including the vertical door/stairwell links between floors. |
| `render.py` | — (not in the paper) | Pure function that renders one (or every occupied) z-level of a `City` as an ASCII grid with agents marked — no I/O, so it's reusable by a future live viewer. |
| `llm.py` | — | Thin wrapper around Ollama's `/api/chat` and `/api/embeddings`. Swap this file to target MLX or llama.cpp instead. |

## Deliberate simplifications (vs. the paper/reference repo)

- **No spatial simulation.** The original has a full maze/pathfinding world;
  here agents have a fixed `location` string for the whole run. Agents only
  ever perceive/interact with others at the *same* location string, so put
  agents who should meet in the same place when constructing them.
- **One level of plan decomposition**, not the recursive
  day → hour → 5-15-minute breakdown in the paper. `planning.decompose()` is
  the place to make it recursive if you want that fidelity.
- **Recency scoring bug fixed.** The reference repo's `retrieve.py` sorts
  memories oldest-first but assigns decay weights in a way that actually
  favors *older* memories over newer ones (a known issue in that codebase).
  `memory.py` computes recency the way the paper describes: newest memories
  score highest, decaying by `0.99` per rank.
- **No `poignancy` caching for identical/duplicate events** and no
  emoji/action-event-triple generation — cut because they're presentation
  details, not core to the architecture.

## Extending

- Add more locations and simple scripted movement to `Agent.location` to get
  agents actually walking around instead of staying put.
- Make `planning.decompose()` recursive for hour- and minute-level granularity.
- Swap `llm.py` for an MLX or llama.cpp backend if you want to skip Ollama.
- Persist `MemoryStream.nodes` to disk (e.g. JSON) between runs for
  multi-day simulations — everything in `memory.MemoryNode` is already a
  plain dataclass.
