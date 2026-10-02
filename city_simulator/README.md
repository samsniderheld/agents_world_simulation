# city simulator

A local Flask app with a node-based canvas UI (React + [React Flow](https://reactflow.dev)),
running on-device via [Ollama](https://ollama.com) by default. Three
generators, wired together on the canvas:

1. **History** (`history/`) — procedurally generates a ~330-year history
   (1624 Dutch colonization → the late 1950s) for a NYC-inspired city: a
   catalog of historical places (taverns, markets, churches, shipyards,
   tenements, theaters), each with a full internally-consistent backstory,
   plus present-day residents grounded in that history, added on demand.
2. **Agents** (`agents/`) — a minimal implementation of the "Generative
   Agents" architecture (Park et al., 2023): agents with a memory stream,
   retrieval, reflection, planning, and reacting/dialogue. A city's
   residents are its agent roster, each placed at their own real grounding
   place from that history — two agents only meet if history genuinely put
   them at the same place (or you convene them somewhere on purpose). A
   finished run can be turned into a film-noir video-vignette *treatment*
   (cast, synopsis, storyboard). Two modes: **SCENE** (a few residents, full
   cognition each) and **CITY** (up to ~200 heroes with full cognition plus
   up to 1000 schedule-driven background residents, on batched concurrent
   LLM calls) -- see [`agents/README.md`](agents/README.md#modes).
3. **Visuals** (`visuals/`) — image, video and music generation (fal.ai
   hosted models, or a local Z-Image Turbo pipeline on Apple Silicon)
   behind the Image, Frame, Video and Music nodes, with a reusable *style*
   library (prompt + reference images) any of them can be wired to.

Everything you generate is persisted to disk by `citystate/` — the cities
themselves, every agent's runs, every entity's media, *and the canvases*
(node positions, wiring, per-node state) — so it all survives a restart.

## Setup

1. Install Ollama, then start it with the helper script (idempotent -- safe
   to run even if it's already up):
   ```bash
   brew install ollama                                  # macOS
   # Linux: curl -fsSL https://ollama.com/install.sh | sh
   ./start_ollama.sh
   ```
   Stop it later with `./stop_ollama.sh`.
2. Pull a chat model and the embedding model (the agent side uses embeddings
   for memory retrieval; the history side doesn't). `agents/config.py` and
   `history/config.py` each auto-detect the machine's available memory
   (`hardware.py`) and pick a model sized to it -- pull whichever tier
   applies, adjusting the tier list to taste (`history/data/config.yaml`'s
   `chat_model_tiers`, or `agents/config.py`'s `_CHAT_MODEL_TIERS`):
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
4. Build the frontend (Node 20+). Only needed once, and again after any
   change under `frontend/` -- see [`frontend/README.md`](frontend/README.md):
   ```bash
   (cd frontend && npm install && npm run build)
   ```
5. For image/video/music generation, `visuals/`'s **fal.ai** provider
   needs an API key from [fal.ai](https://fal.ai/dashboard/keys) (`FAL_KEY`
   is fal's own env var convention -- never put this in a committed file).
   Easiest via a `.env` file, loaded automatically:
   ```bash
   cp .env.example .env
   # then edit .env and set FAL_KEY=...
   ```
   or just export it directly (a real `export`ed value always wins over
   `.env`). There's also a **local** provider (Apple Silicon only -- Z-Image
   Turbo via Diffusers/MPS, no API key needed, text-to-image only), off by
   default. Switch to it by setting `visuals/data/config.yaml`'s `provider`
   to `local`, after installing its separate, several-GB dependency set:
   ```bash
   pip install -r requirements-local-visuals.txt
   ```
   First use downloads the model; see `visuals/NOTES.md` for the
   hardware/memory details this was built against.
6. Ollama is the default for the Agents side too, but a Simulation or
   Treatment node's provider picker can switch that call to the **Claude
   API** instead (`agents/providers/claude.py`) -- needs its own key, same
   `.env` pattern as `FAL_KEY`:
   ```bash
   export ANTHROPIC_API_KEY=...
   ```
   The picker also offers **OpenAI-compatible (MLX / vLLM / SGLang)**
   (`agents/providers/openai_compat.py`), for a faster local server that
   batches many requests at once. Start one, then point the app at it:
   ```bash
   mlx_lm.server --model mlx-community/Meta-Llama-3.1-8B-Instruct-4bit   # port 8080, the default
   # or: vllm serve <model>                          -> OPENAI_COMPAT_BASE_URL=http://localhost:8000/v1
   # or: python -m sglang.launch_server --model-path <model>  -> http://localhost:30000/v1
   ```
   Memory retrieval still needs Ollama's embedding model either way --
   neither Claude nor these servers are used for embeddings, so picking
   one only swaps out the chat/dialogue/planning calls, not
   `nomic-embed-text`.
7. Run it:
   ```bash
   python3 app.py
   ```
   Serves at `http://127.0.0.1:8420` -- a fixed port (`app.py`'s `PORT`),
   so the URL survives a restart and you can refresh an existing tab (it
   doesn't auto-open a browser). Frontend-only changes just need `npm run
   build` + a refresh; backend changes need the Flask process restarted.

## Running on a cloud GPU

For CITY mode at full scale (hundreds of agents): a Linux box with an NVIDIA
GPU runs three things side by side -- **vLLM** (the chat model, for both
CITY tiers and optionally SCENE and treatments), **Ollama** (memory
embeddings and history generation, both small), and the app. An 80 GB card
(H100, A100 80GB, H200) is the sweet spot. CITY mode against vLLM is built
to the documented OpenAI-compatible API and tested against a stub server,
not yet against real vLLM -- the first run will tell you if anything's off.

1. **The box**: Ubuntu 22.04+ with the NVIDIA driver (most GPU images have
   it; check `nvidia-smi`), Python 3.10+, Node 20+, git. Clone the repo and
   check out this branch.
2. **Ollama**, kept small so vLLM gets the GPU:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh     # installs and starts a service
   ollama pull nomic-embed-text                      # memory embeddings (required)
   ollama pull llama3.1:8b                           # history generation, Ollama SCENE runs
   ```
3. **vLLM**, in its own virtualenv (it pins its own torch/CUDA):
   ```bash
   python3 -m venv ~/vllm && ~/vllm/bin/pip install vllm
   ~/vllm/bin/vllm serve Qwen/Qwen3-30B-A3B-Instruct-2507-FP8 \
     --port 8000 --max-model-len 8192 --gpu-memory-utilization 0.80
   ```
   Wait for "Application startup complete" (the first start downloads
   ~30 GB). `0.80` leaves room on the card for Ollama. A mixture-of-experts
   model like this one is fast per token for its size, which is what a city
   of agents needs. One server is enough: the background tier's own model
   isn't served there, so CITY falls back to the same model for both tiers
   (a status line in the run log says so). To give the background tier a
   smaller model, start a second `vllm serve` on port 8001 with a lower
   `--gpu-memory-utilization` and set `CITY_BACKGROUND_BASE_URL` below.
4. **The app**:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   (cd frontend && npm install && npm run build)
   cp .env.example .env
   ```
   and in `.env`:
   ```bash
   OPENAI_COMPAT_BASE_URL=http://localhost:8000/v1
   OLLAMA_CHAT_MODEL=llama3.1:8b     # otherwise an 80 GB card auto-picks gpt-oss:120b in Ollama
   FAL_KEY=...                       # only for image/video nodes
   # CITY_BACKGROUND_BASE_URL=http://localhost:8001/v1   # if you run a second vLLM
   ```
   then `python3 app.py`.
5. **Open it from your laptop.** The app only listens on localhost (it has
   no login -- don't expose it publicly), so tunnel the port:
   ```bash
   ssh -L 8420:localhost:8420 you@your-gpu-box
   ```
   and browse to `http://localhost:8420`.
6. **In the app**: on a City Simulation node, *hardware* auto-detects the
   card (70 GB+ is the `h100` profile: up to 2000 agents, 256 requests in
   flight; 24-70 GB is `rtx5090`: 1000 agents, 128 in flight). Leave the
   tiers on *profile default* -- or type the served model name to skip the
   fallback note. For Simulation and Treatment nodes, pick
   **OpenAI-compatible** to use vLLM too.

### On RunPod

**Which GPU.** Pick a *Pod* (not Serverless) in a region with the card you
want:

| Goal | GPU | Model (`VLLM_MODEL`) | CITY profile it gets | Agents |
|---|---|---|---|---|
| Recommended | **H100 80GB** (SXM or PCIe), A100 80GB | `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` (the default) | `h100`: 256 in flight | up to 2000 |
| Cheaper, still good | L40S 48GB, RTX 6000 Ada 48GB | the same model, `VLLM_GPU_UTIL=0.85` | `rtx5090`: 128 in flight | ~1000 |
| Just trying it | RTX 4090 24GB, RTX 5090 32GB | `Qwen/Qwen3-8B-FP8` | `rtx5090` | a few hundred |
| Biggest heroes | H200 141GB | `openai/gpt-oss-120b` | `h100` | up to 2000 |

An 80 GB card fits the recommended model with plenty of room for many
agents' requests at once (its KV cache) plus Ollama beside it; a 48 GB card
fits it with less headroom. On a 24-32 GB card the 30B model doesn't leave
enough room, so use an 8B model. The A100 has no native FP8, but vLLM still
runs FP8 weights on it (a little slower than on H100).

**Template and pod settings.**

| Setting | Recommendation |
|---|---|
| Template | **RunPod PyTorch** (Ubuntu 22.04, CUDA 12.x; any 2.4+ tag). It has Python and the NVIDIA stack; the setup script adds the rest. |
| Container disk | 40 GB (system packages; wiped on every restart) |
| Volume disk (`/workspace`) | **150 GB** -- the vLLM model (~30 GB), Ollama models (~6 GB), the two virtualenvs (~15 GB), your cities, with room for a second model |
| Exposed ports | TCP **22**, with *SSH over exposed TCP* / public IP on, so you can tunnel. Expose HTTP 8420 only with the app's login on (see *As a public website* below). |
| Environment variables | none needed; optionally `VLLM_MODEL`, `VLLM_GPU_UTIL`, `FAL_KEY` |

**Setup** (in the pod's web terminal, or over SSH):

```bash
cd /workspace
git clone https://github.com/samsniderheld/agents_world_simulation.git
cd agents_world_simulation && git checkout improving_agents
bash city_simulator/deploy/runpod/setup.sh     # ~15-25 min the first time (downloads)
bash city_simulator/deploy/runpod/start.sh     # starts Ollama, vLLM, the app; prints the tunnel command
```

`setup.sh` installs Node, Ollama and vLLM, builds the frontend, writes
`.env` (vLLM URL, a small Ollama chat model), and downloads the models into
`/workspace` so they survive a restart. For a different model:
`VLLM_MODEL=Qwen/Qwen3-8B-FP8 bash .../setup.sh` (and the same variable for
`start.sh`). The first `start.sh` takes a while after the weights load:
vLLM compiles kernels and captures CUDA graphs (15-30 min is possible on
H100); the result is cached under `/workspace/vllm-cache`, so later starts
are quick. To skip it, `VLLM_EXTRA_ARGS=--enforce-eager bash .../start.sh`
(serves somewhat slower). Add `FAL_KEY=...` to `city_simulator/.env` for image/video
nodes. Then, on your laptop:

```bash
ssh -L 8420:localhost:8420 root@<pod-ip> -p <ssh-port> -i ~/.ssh/<your-key>
```

and open `http://localhost:8420`. Logs are in `/workspace/logs/`
(`vllm.log`, `ollama.log`, `app.log`).

**As a public website** (instead of the tunnel): RunPod can give the pod a
public HTTPS address, but then anyone with the link reaches the app -- so
turn on its login first. In `city_simulator/.env` on the pod:

```bash
APP_HOST=0.0.0.0          # listen beyond localhost (refused without a password)
APP_USER=admin
APP_PASSWORD=<something long>
```

restart the app (`pkill -f app.py; bash city_simulator/deploy/runpod/start.sh`),
then in RunPod edit the pod and add **8420** under *Expose HTTP Ports*. The
site is `https://<pod-id>-8420.proxy.runpod.net`; the browser asks for the
user and password once. Editing a pod's ports restarts it, so run
`setup.sh` and `start.sh` again afterwards.

**After a `git pull`** on the pod: `pkill -f app.py; bash city_simulator/deploy/runpod/start.sh`
-- it rebuilds the frontend if its source changed and restarts the app; then
hard-refresh the browser.

**After a pod restart** everything outside `/workspace` is gone: rerun
`setup.sh` (a few minutes -- it only reinstalls system packages; venvs and
models are kept), then `start.sh`. **Stop the pod** when you're done --
RunPod bills a running pod by the hour, and a stopped pod only for its
volume. Your cities live in `/workspace/.../citystate/data`, so they're
kept while the volume exists; copy that folder off the pod before you
delete it.

These scripts follow RunPod's standard pod layout but haven't been run on
RunPod yet; if a step fails, its output says which.

To measure the box before a real run (needs an active city):

```bash
python3 -m agents.city.bench --real --profile h100 --agents 200 1000 --ticks 4
```

Everything also works without Ollama running: the New City modal's "Use
LLM" checkbox, unticked, falls back to pure-grammar names/prose, and
starting a simulation raises a clear error if the configured model isn't
pulled (or, with Claude picked, if `ANTHROPIC_API_KEY` isn't set -- checked
up front, before any simulation work starts). Without `FAL_KEY` set (and no
local provider configured), a generation starts normally but its status
flips to an error the moment fal.ai is actually called.

## Using it

**Cities** (`/`) lists every generated city as a card, with the theme it was
made with. "+ New City" opens a config modal (theme, seed, figures per era,
events per figure, use LLM) and kicks off generation as a background job; "open" activates that city and takes
you to its canvas; "delete" asks for confirmation, then permanently removes
it.

**A city's canvas** (`/c/<city>`) is a React Flow graph. The left drawer
lists every node type plus the city's residents and places not yet on the
canvas (drag or "+" to add); the right Inspector shows the city overview,
chronicle and generation log, or the selected agent's/place's detail and
media. Double-click an Agent or Location node (or its ⤢ button) to drill
into that entity's own canvas (`/c/<city>/agent/<id>`, `/c/<city>/place/<id>`).
The header's **Gallery** button opens a card view of all agents and
locations (`/c/<city>/gallery`); each card's hide toggle drops that entity
from every canvas's "add" drawer without touching anything already placed
(78 locations is too many to scroll). **Scratch** opens a global board that
belongs to no city (`/scratch/default`). Esc or the breadcrumb always goes
up one level -- back to wherever you came from.

Editing the graph: drag on empty canvas to box-select, Delete/Backspace
removes the selection; two-finger scroll or Space + drag pans, pinch or
⌘ + scroll zooms. Click a cord to select it (it turns yellow). Hover a cord
to see the grab dots at its ends: drag one onto another compatible port to
move the cord, or drop it anywhere else to remove it.

Node types, and how they wire together (`frontend/src/flow/edgeRules.ts`
is the one table of allowed connections; port colors follow
`flow/nodes/portTypes.ts`):

| Node | Ports | What it does |
|---|---|---|
| **Agent** | `agent:out`, `run:out`; `style:in` | A resident. Has its own "▶ run" for a single-agent simulation. |
| **Location** | `place:out`; `style:in` | A place. |
| **Population** | `character-style:in`, `location-style:in` | One number, N: picks N of the city's locations (ones with no resident first, then ones without an exterior photo, newest first) and gives each a new resident who belongs there -- grounded at that place, so their bio and life history come from its founder and recorded history -- with a square portrait, plus a square exterior photo of the place if it has none (1024×1024, the image model's smallest size). A Style wired into *char style* applies to every portrait, one wired into *place style* to every exterior. Everything is generated in parallel (6 at a time; one at a time with the local image provider), as a background job with progress and a stop button; images attach to each agent's/place's media. Locations aren't created -- a city's places come from its history. |
| **Simulation** | `agents:in` (many), `place:in`; `run:out` | Runs a tick loop for the connected agents. A connected Location *convenes* them there instead of at their own grounding places. Ticks, a free-text directive to steer the interaction, provider/model, a verbose/actions-and-dialogue-only log filter, and *dice & DM* (stats, tasks that can fail, d20 checks, narrated consequences -- see `agents/README.md`). |
| **City Simulation** | `agents:in` (many: the heroes), `place:in`; `run:out` | CITY mode: the wired agents (or, with none wired, every resident) are heroes with full cognition, plus N background residents generated from the city's own data who follow daily schedules. Hardware profile (Mac/Ollama, RTX 5090 or H100 with vLLM) and per-tier provider/model, ticks/length/start, directive, a "persist hero memories" toggle, *dice & DM*. While running: pause/resume/stop, per-tick metrics (time per wave, requests, tok/s, failures), the residents most involved with the heroes (promote any of them to hero), and a heroes-only or everyone log. Paused or finished: *zoom into a scene* picks a place and time window and creates a Simulation node wired with whoever was there. |
| **Treatment** | `run:in`, `agent:in`, `place:in`, `style:in`; `treatment:out`, `shots:out` | Turns the connected run's transcript into a film treatment (provider/model selectable). Connected Agents/Locations feed the LLM their real bios (with appearance/wardrobe) and architecture descriptions as `CAST:`/`SETTING:` context. "▶ create storyboard" creates a **Storyboard** node seeded with one Frame per parsed shot. |
| **Storyboard** | `shots:in`, `agent:in`, `place:in`, `style:in` | A container with its own canvas (`/storyboard/<id>`): the seeded Frame nodes, laid out in one row, each already wired to whatever Agent/Location/Style the Treatment had connected -- the same connections are redrawn to the Storyboard node itself on the outer canvas. The node shows thumbnails of its generated frames. |
| **Image** | `image:in`, `agent:in`, `place:in`, `shot:in`, `style:in`; `image:out` | The one image node. Generates from its prompt (16:9, 9:16 or square) with any wired Style, Agent/Location photos, and input Images as references; *edit image* changes the current picture with a second prompt. The result stays on the node, or -- with *save to ... media* ticked, the default on an agent's or place's own canvas -- goes into that entity's media (its thumbnail, media grid, and other images' references). Storyboards seed one per shot (header "Shot 03"). Older Frame, agent/place Image and freeform Image nodes load as this one. |
| **Photo** | `image:out` | An image from your computer: choose a file or drop one onto the node (uploaded to `visuals/data/uploads/`). Wire it into an Image node (a reference, or the picture to edit) or a Video node (to animate it). |
| **Video** | `image:in`, `style:in`; `video:out` | Image-to-video from an Image or Photo node (16:9 or 9:16). |
| **Music** | none | Text-to-music (Lyria 2) on any canvas; the result lives on the node. |
| **Style** | `style:out` | A library entry: a style prompt plus reference images. Many can feed one port (prompts joined, references concatenated). Shared across every city and board. |
| **Text** | `text:in` | Read-only viewer for a Treatment's full text. |

**Saved graphs.** Every canvas's drawer has a *Saved graphs* section.
"+ Save this canvas" stores a named copy of everything on it, including the
inner canvas of each Storyboard. Click a saved graph to load it: *Add to
canvas* places a copy to the right of what's there, *Replace canvas* clears
the canvas first. Loaded nodes get fresh ids (a Storyboard gets a new inner
canvas), so every load is independent of the saved copy and of other loads;
Agent and Location nodes keep theirs, since they point at real residents and
places. The library is global, like styles, so a setup saved in one city can
be loaded into another, where its residents show up as Missing.

Every node type is available on every canvas. Every canvas autosaves
(600 ms debounce) to its own graph document, `PUT /api/graph/<scope>`; a
saved Agent/Location node whose entity no longer exists (a regenerated or
deleted city) reconciles to a *Missing* node you can remove, never
silently dropped.

## Layout

```
city_simulator/
  app.py             Flask app factory + entrypoint (python3 app.py):
                       registers every blueprint, serves static/dist/
  jsonutil.py        shared JSON-response helper for every blueprint
  hardware.py        shared hardware-memory detection (both configs use it)

  frontend/          the React + TypeScript + Vite single-page app --
                       see frontend/README.md for its own layout
  static/dist/       `npm run build`'s output (gitignored); what app.py serves

  history/           the history-generation engine + its API
    README.md          how the generator works, with a worked example
    data/              every YAML file -- edit these, not the .py files
      config.yaml        technical knobs (counts, seed, LLM fill, model tiers);
                         the world itself is in a theme file (themes/)
    config.py, llm.py, log.py
    eras.py, entities.py, events.py, grammar.py, names.py, architecture.py
    characters.py, summary.py
    generate.py        run_history() + a standalone CLI
    jobs.py            background-thread job state
    routes.py          Blueprint: /api/history/*

  theme.py           city themes: load, validate, render prompts; theme_routes.py: /api/themes
  themes/            built-in themes: noir_nyc.yaml (default), fantasy_realm.yaml

  agents/            the agent-simulation engine + its API
    README.md          how the agents work: memory, reflection, planning, the tick
                         loop, and the two modes (SCENE, CITY)
    config.py, llm.py, providers/ (ollama.py, claude.py, openai_compat.py)
    gateway.py         CITY mode's async batched inference layer
    city/              CITY mode: world.py (the wave loop), run.py, prompts.py,
                         tiers.py, population.py, zoom.py, recorder.py, bench.py
    agent.py, memory.py, planning.py, reflection.py, world.py
    recorder.py, display.py, textutil.py
    simulation.py      run(), roster_from_history()
    treatment.py       post-run treatment + storyboard-shot parsing
    jobs.py            background-thread job state
    routes.py          Blueprint: /api/agents/*

  visuals/           image/video/music generation backend + the style library
    NOTES.md           local-generation research: verified pipeline
                       classes, repo ids, settings, what's blocked
    data/
      config.yaml      default provider, fal model ids, poll/timeout,
                       image/video/local generation defaults
      styles.json      the style library (gitignored; user-created)
      uploads/, outputs/  uploaded/generated files (gitignored)
    config.py          loads config.yaml; FAL_API_KEY from $FAL_KEY
    providers/         base.py (the Provider interface), fal.py, local.py
    storage.py         save_url() / save_pil_image() / save_upload()
    styles.py          the style library's CRUD
    jobs.py            background-thread job state (one slot)
    routes.py          Blueprint: /api/visuals/*
    styles_routes.py   Blueprint: /api/styles/*

  citystate/         everything persisted -- cities, media, and canvases
    data/              generated (gitignored): cities/<id>/{city.json,
                       locations.json, agents/<id>/agent.json, media/},
                       active_city, graphs/<scope>.json
    store.py           the city collection + the active city
    routes.py          Blueprint: /api/city/*
    graph_store.py     one JSON document per canvas scope
    graph_routes.py    Blueprints: /api/graph/*, /api/graph-library/*
    graph_library.py   named saved graphs (data/library/<id>.json)

  tests/             python3 -m unittest discover -s tests -t .  (stdlib only;
                       includes the SCENE regression snapshot)
```

`history/`, `agents/`, `visuals/`, and `citystate/` are plain Python
packages (relative imports between their own modules); `hardware.py`/
`jsonutil.py` stay at the project root since more than one package/
blueprint needs them.

## How it works

```text
frontend (React Flow canvases; frontend/src/)
  |
  |-- "+ New City" --> POST /api/history/generate --> history/jobs.start()
  |                      |                              |
  |                      |                              `-- history/generate.py's run_history()
  |                      |                                    |-- generate()               schedule + resolve every Figure's
  |                      |                                    |                             life events in chronological order
  |                      |                                    |-- summary.generate_summary() one LLM call over the whole record
  |                      |                                    `-- citystate.store.replace()  a new city in the collection,
  |                      |                                                                    now the active one
  |                      v
  |                    GET /api/history/status (poll) --> GET /api/history/data --> the canvas's drawer + Inspector
  |
  |-- "+ New agent" --> POST /api/history/characters/preview (draft) --> POST /api/history/characters (save)
  |                                                                       `-- characters.generate_character(): grounded
  |                                                                           in one real place; bio includes appearance
  |
  |-- Simulation node "▶ run" --> POST /api/agents/run --> agents/jobs.start() --> simulation.run()
  |                                  |                                                |-- build_agents()   the connected residents
  |                                  |                                                |-- world.World.run() tick loop: plan / decompose,
  |                                  |                                                |                     perceive + react (+ dialogue), reflect
  |                                  |                                                `-- citystate.store.append_agent_run()
  |                                  v
  |                                GET /api/agents/state, /events (poll) --> the node's live log
  |
  |-- Treatment node "▶ generate" --> POST /api/agents/treatment --> treatment.generate_treatment()
  |                                     (agent_ids/place_ids -> CAST:/SETTING: blocks)   `-- GET /treatment/shots -> shot list
  |
  |-- Frame / Image / Video / Music "▶ generate" --> POST /api/visuals/generate-* --> visuals/jobs.start()
  |                                                     |                                `-- providers.get_provider(): fal or local
  |                                                     v
  |                                                   GET /api/visuals/status (poll) --> GET /api/visuals/result
  |                                                     `-- Image node only: POST /api/city/media (attach to the entity)
  |
  `-- every canvas edit --> (600ms) PUT /api/graph/<scope>  (citystate/graph_store.py)
```

`history/jobs.py`, `agents/jobs.py`, and `visuals/jobs.py` each run their
half's work on its own background thread with its own status, so
generating a history, running agents, and generating media are all
independent jobs (though `visuals/jobs.py` has only one job slot, shared by
every media node). The frontend's `state/jobStore.ts` polls all three from
the app root, so a running job keeps showing as running while you navigate.
`history/routes.py`'s `POST /api/history/generate` hands
`agents/jobs.py`'s `set_history_roster` to `history/jobs.py` as an on-done
callback -- one of the few places these packages touch. `citystate/` is the
other: `history/jobs.py`, `agents/simulation.py`, and `app.py` (to hydrate
the agent roster from the active city at startup) all call through
`citystate.store`.

## Architecture

| File(s) | Half | What it does |
|---|---|---|
| `app.py` | all | Flask app factory + entrypoint: registers every blueprint, serves the built SPA from `static/dist/` for every non-`/api` path, hydrates the agent roster from the active city (if any) at startup. |
| `frontend/` | ui | The whole interface; see `frontend/README.md`. The parts worth knowing about from the backend's side: `api/client.ts` (every endpoint the UI calls, typed), `routes/router.ts` (the URL-per-canvas scope router), `flow/edgeRules.ts` (which ports connect), `flow/pipeline.ts` (what each node derives from its connections), `flow/usePersistedGraph.ts` (autosave). |
| `history/data/config.yaml` / `history/config.py` / `history/llm.py` | history | Every tunable knob (LLM behavior, figure/event counts) lives in `data/config.yaml`; `config.py` just loads it and picks a chat-model tier for this machine. `llm.py` is a thin Ollama chat wrapper, tuned for many short name/prose-fill calls. |
| `history/eras.py`, `entities.py`, `events.py`, `grammar.py`, `names.py`, `architecture.py` | history | The procedural-history engine itself -- modeled on Jason Grinblat's GDC talk on Caves of Qud's mythic-biography generator: entities as mutable-property bags, events resolved by reading current state (not simulated causality), text produced by a real replacement grammar (`grammar.py`). All *content* comes from the city's theme file (`theme.py`, `themes/`); the `.py` files hold only behavior. See `history/README.md`. |
| `theme.py` / `theme_routes.py` / `themes/` | all | City themes: one YAML file per world (eras, names, place types, events, architecture, residents, city life, every LLM prompt). `theme.py` loads, validates and renders them and picks the active city's; `/api/themes` lists, uploads and downloads them. |
| `history/characters.py` | history | Present-day residents, each grounded in one real place's founder/domain/history, with a bio that includes physical appearance and wardrobe (so image generation has something to work from). Generated on demand from the UI ("+ New agent": preview, edit, save), not as part of city generation. |
| `history/summary.py` | history | One LLM call at the very end of a run: a short narrative summary of the city's history (the Inspector's overview). Falls back to a plain stats sentence with no LLM. |
| `history/generate.py` | history | `run_history()` (called by `jobs.py`) and a standalone CLI (`python3 -m history.generate --seed 42`) that does the same thing plus writes `history.json`/`characters.json`. |
| `history/population.py` | history | The Population node's job: N locations, each given a new resident via `characters.generate_one(force_place_id=...)`, then a square (1:1) image per resident and per chosen location from the active visuals provider at its native 1024×1024, attached with `citystate.add_media()` (tagged `portrait` / `exterior`). Styles are applied as for an Image node (prompt joined on, reference images as input images). Work runs on a thread pool (`MAX_PARALLEL`, 1 for the local provider); the fal provider keeps one HTTP session per thread for this. `/api/history/population` (start, status, stop); city generation refuses to start while it runs. |
| `history/jobs.py` / `routes.py` / `log.py` | history | Background-thread job orchestration, the `/api/history/*` blueprint (generate, the city collection, characters), and the progress log the Inspector shows live. |
| `agents/config.py` / `agents/llm.py` / `agents/providers/` | agents | Config (recency/reflection/retrieval tuning, from the reference implementation). `llm.py` is a thin dispatcher to whichever `providers/` backend a run asked for (`ollama.py` default, `claude.py` -- raw REST to the Messages API, no SDK dependency); every other agents/ file just calls `llm.complete()` and never knows a provider swap is possible. `embed()` always goes to `ollama.py`, since Claude has no embeddings endpoint. |
| `agents/agent.py`, `memory.py`, `planning.py`, `reflection.py`, `world.py` | agents | The generative-agents cognitive core -- memory stream + retrieval, reflection, planning, reacting/dialogue, and the tick-based simulation loop. A run's optional free-text *directive* is threaded into planning and reactions. See each file's docstring. |
| `agents/simulation.py` | agents | `run()` and `roster_from_history()` -- restages a city's residents as agents, each at their own real grounding place unless the run convenes them at one Location. |
| `agents/jobs.py` / `routes.py` | agents | Background-thread job orchestration and the `/api/agents/*` blueprint (run/stop/state/events, providers/models, treatment). |
| `agents/treatment.py` | agents | One LLM call after a run: a film-noir video-vignette treatment (cast, synopsis, storyboard) over the *merged* transcript of every agent in that run, with explicit `CAST:`/`SETTING:` blocks built from the connected agents' bios and places' architecture. `parse_storyboard_shots()` splits its STORYBOARD section into one prompt per shot (each carrying a `Character:` description, so it works standalone as an image prompt). |
| `agents/recorder.py` / `display.py` / `textutil.py` | agents | Structured event log the frontend polls (`recorder.py`; also folded into each agent's persisted record once a run finishes), terminal color helpers for `--verbose` tracing (`display.py`), small text-parsing helpers (`textutil.py`). |
| `visuals/data/config.yaml` / `visuals/config.py` | visuals | Default provider (`fal` or `local`), fal.ai model ids, poll/timeout, image/video/local generation defaults. The fal API key is deliberately *not* here -- `config.py` reads it from the `FAL_KEY` environment variable (or a `.env` file at the project root, via `python-dotenv`; see `.env.example`). |
| `visuals/providers/base.py` | visuals | The `Provider` interface (`generate_image()`, `generate_video()`, `generate_video_from_reference()`, `generate_music()`) every backend implements. |
| `visuals/providers/fal.py` | visuals | `FalProvider` -- submits to fal.ai's queue REST API, polls until done, fetches the result, and downloads it locally via `storage.py`. Text-to-image, image-edit (used automatically when reference images are given), image-to-video, reference-to-video, and text-to-music (Lyria 2). |
| `visuals/providers/local.py` | visuals | `LocalProvider` -- Z-Image Turbo via Diffusers on PyTorch's MPS backend. bfloat16, SDNQ int8 quantization, CPU offload, one-time warmup. Text-to-image only (raises a clear error for the rest). See `visuals/NOTES.md`. |
| `visuals/providers/__init__.py` | visuals | `get_provider(name=None)` -- memoized per provider name, so switching backends doesn't discard an already-loaded pipeline. Falls back to `config.PROVIDER`. |
| `visuals/storage.py` | visuals | Saves uploaded/downloaded/generated bytes under `data/uploads/` or `data/outputs/` with a uuid filename; provider-agnostic. An Image node's result is then relocated by `citystate.store.add_media()` into the owning entity's own directory; Frame/Video/scratch results stay here and are referenced by their nodes. |
| `visuals/styles.py` / `styles_routes.py` | visuals | The global style library (`data/styles.json`) behind Style nodes and the drawer's Styles section: name, style prompt, reference images (uploaded via `/api/visuals/upload`). Global on purpose -- reusable across cities and boards, untouched by deleting a city. |
| `visuals/jobs.py` / `routes.py` | visuals | Background-thread job orchestration (one slot) and the `/api/visuals/*` blueprint: the four `generate-*` endpoints, `/upload`, `/files/<path>`, `/status` + `/result`, and `GET /providers` (with per-provider capabilities, e.g. whether reference images are supported) + `POST /provider` for switching the active backend at runtime. |
| `citystate/store.py` | citystate | The city collection under `data/cities/<id>/` and the *active* one (`data/active_city`) that every implicit-city endpoint reads. Each city is `city.json` (eras/figures/events/summary) + `locations.json` + one `agents/<id>/agent.json` per resident, each entity with its own `media/` directory alongside. Atomic writes, lazy-loaded. `get()` composes one dict shaped like a single-blob city so no reader sees the split. |
| `citystate/routes.py` | citystate | The `/api/city/*` blueprint: `GET /agents/<id>` (one agent's full record, including persisted `plans`/`runs`), `POST /media` / `DELETE /media/<entity_id>/<media_id>`, and `GET /files/<path>` serving the relocated media. |
| `citystate/graph_store.py` / `graph_routes.py` | citystate | The canvases: one JSON document per scope (`city:<id>`, `agent:<id>`, `place:<id>`, `scratch:<board>`, `storyboard:<id>`) under `data/graphs/`, with a `rev` for optimistic concurrency (`GET`/`PUT /api/graph/<scope>`). Deliberately opaque -- stores whatever `nodes`/`edges` the client sends; what a node *means* is entirely the frontend's business. |
| `citystate/graph_library.py` | citystate | The *Saved graphs* library (`/api/graph-library/*`): named bundles of a canvas's nodes/edges plus every Storyboard's inner canvas, under `data/library/`. Opaque like `graph_store.py`; `frontend/src/flow/useGraphLibrary.ts` does the capture on save and the id remapping on load. |
| `hardware.py` | history, agents | Detects available memory (Apple unified memory or NVIDIA VRAM) so each config can size its chat model to the machine it's running on. |
| `jsonutil.py` | all | Shared `json_response()` helper every blueprint uses. |

## Themes

Everything that gives a city its world lives in one YAML **theme** file:
its eras and present year, name pools and naming patterns, domains,
factions, roles and place types, the event templates that write its
history, architecture, resident templates, CITY-mode city life (jobs per
place type, homes, haunts, routines, small talk), the fallback cast, the
visual look, and every prompt the app sends a language model. Two are
built in: `themes/noir_nyc.yaml` (the default: New Amsterdam in 1624 to a
film-noir New York in 1959) and `themes/fantasy_realm.yaml` (the free city
of Aldermere, 1000-1312). Technical settings -- models, concurrency,
timeouts, memory weights -- are not part of a theme.

**Making one:** in the New City dialog, pick a theme and *download this
theme*, edit it (its header and comments explain each section), and
*upload a theme…*. An upload is checked before it's accepted -- missing
sections, eras without names or architecture, jobs at place types that
don't exist, a prompt using a `{slot}` the app doesn't fill or dropping a
reply marker the app reads (`NAME:`, `WHERE:`, `STORYBOARD:`...) -- and a
small test history is generated with it; every problem is listed.
`GET /api/themes/reference` lists every prompt and the slots it can use.
The Dice & DM prompts (`prompts.dm`) and the background dice table
(`city_life.dice`) are optional: a theme without them uses the default
theme's.

**Per city:** a city keeps its own copy of the theme it was generated
with (`citystate/data/cities/<id>/theme.yaml`, downloadable from its card),
and everything for that city -- history, residents, both simulation modes,
treatments, image prompts -- uses it. Editing or removing a theme later
never changes an existing city. Cities from before themes use the default.

## Tests and benchmark

```bash
python3 -m unittest discover -s tests -t .   # everything, against stub LLMs; nothing touches your cities
python3 -m agents.city.bench                 # CITY at 50/200/500/1000 agents on a stub server
```

`tests/test_scene_regression.py` snapshots a SCENE run (event sequence and
every prompt, against a deterministic stub): if it fails, SCENE's behaviour
changed. `tests/test_theme_golden.py` does the same for everything the
theme drives (history, CITY), and `tests/test_dm_scene.py` /
`tests/test_dm_city.py` for seeded runs with dice & DM on. Re-record
deliberately with `UPDATE_GOLDEN=1`.

## Extending

- **A new node type**: a component in `frontend/src/flow/nodes/`, a case in
  `flow/pipeline.ts` (persisted shape in/out, plus whatever it derives from
  its connections in `enrichPipelineNodes`), its ports' allowed connections
  in `flow/edgeRules.ts`, and a drawer entry in `flow/useAddNodeActions.ts`
  -- then register it in each canvas's `nodeTypes`. The backend never needs
  to know: `graph_store.py` stores nodes opaquely.
- **A new visuals provider**: a `visuals/providers/*.py` implementing
  `Provider`, registered in `providers/__init__.py`'s `get_provider()` and
  `AVAILABLE_PROVIDERS` -- `jobs.py`/`routes.py` don't change. Declare what
  it can't do via the capabilities `GET /api/visuals/providers` reports, and
  the nodes adapt (a Style node hides its reference-image upload when the
  active provider doesn't support them).
- `LocalProvider` only supports Z-Image Turbo text-to-image today. See
  `visuals/NOTES.md` before adding FLUX.2 or Qwen-Image support -- both were
  researched and are currently blocked or not real as specced; that file
  has the exact repo ids/pipeline classes/versions to re-verify against.
- See `history/generate.py`'s and `agents/world.py`'s "Deliberate
  simplifications" notes (in their docstrings) for known scope cuts worth
  revisiting.
