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
   (cast, synopsis, storyboard).
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
   brew install ollama
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
   Memory retrieval still needs Ollama's embedding model either way --
   Claude has no embeddings endpoint, so picking it only swaps out the
   chat/dialogue/planning calls, not `nomic-embed-text`.
7. Run it:
   ```bash
   python3 app.py
   ```
   Serves at `http://127.0.0.1:8420` -- a fixed port (`app.py`'s `PORT`),
   so the URL survives a restart and you can refresh an existing tab (it
   doesn't auto-open a browser). Frontend-only changes just need `npm run
   build` + a refresh; backend changes need the Flask process restarted.

Everything also works without Ollama running: the New City modal's "Use
LLM" checkbox, unticked, falls back to pure-grammar names/prose, and
starting a simulation raises a clear error if the configured model isn't
pulled (or, with Claude picked, if `ANTHROPIC_API_KEY` isn't set -- checked
up front, before any simulation work starts). Without `FAL_KEY` set (and no
local provider configured), a generation starts normally but its status
flips to an error the moment fal.ai is actually called.

## Using it

**Cities** (`/`) lists every generated city as a card. "+ New City" opens a
config modal (seed, figures per era, events per figure, use LLM) and kicks
off generation as a background job; "open" activates that city and takes
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

Node types, and how they wire together (`frontend/src/flow/edgeRules.ts`
is the one table of allowed connections; port colors follow
`flow/nodes/portTypes.ts`):

| Node | Ports | What it does |
|---|---|---|
| **Agent** | `agent:out`, `run:out`; `style:in` | A resident. Has its own "▶ run" for a single-agent simulation. |
| **Location** | `place:out`; `style:in` | A place. |
| **Simulation** | `agents:in` (many), `place:in`; `run:out` | Runs a tick loop for the connected agents. A connected Location *convenes* them there instead of at their own grounding places. Ticks, a free-text directive to steer the interaction, provider/model, and a verbose/actions-and-dialogue-only log filter. |
| **Treatment** | `run:in`, `agent:in`, `place:in`, `style:in`; `treatment:out`, `shots:out` | Turns the connected run's transcript into a film treatment (provider/model selectable). Connected Agents/Locations feed the LLM their real bios (with appearance/wardrobe) and architecture descriptions as `CAST:`/`SETTING:` context. "▶ create storyboard" creates a **Storyboard** node seeded with one Frame per parsed shot. |
| **Storyboard** | `shots:in`, `agent:in`, `place:in`, `style:in` | A container with its own canvas (`/storyboard/<id>`): the seeded Frame nodes, laid out in one row, each already wired to whatever Agent/Location/Style the Treatment had connected -- the same connections are redrawn to the Storyboard node itself on the outer canvas. The node shows thumbnails of its generated frames. |
| **Frame** | `shot:in`, `agent:in`, `place:in`, `style:in`; `image:out` | One storyboard shot: its prompt is the shot text; generates an image. Connected Agents/Locations contribute their own photos as reference images, alongside the Style's. |
| **Video** | `image:in`, `style:in`; `video:out` | Image-to-video from a generated Frame. |
| **Image** | `agent:in`, `place:in`, `style:in`; `image:out` | Free-form image generation on an agent's/place's own canvas; the result attaches to that entity's media. |
| **Freeform image / Music** | `style:in`; `image:out` | Scratch-board generation (image; text-to-music) with no entity to attach to -- the result lives on the node itself. |
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
      config.yaml        every tunable knob
      eras.yaml, entities.yaml, names.yaml, events.yaml, characters.yaml,
      architecture.yaml  content: eras, domains/factions/roles/place
                         types, name word lists, event templates, bio
                         templates, architectural styles
    config.py, llm.py, log.py
    eras.py, entities.py, events.py, grammar.py, names.py, architecture.py
    characters.py, summary.py
    generate.py        run_history() + a standalone CLI
    jobs.py            background-thread job state
    routes.py          Blueprint: /api/history/*

  agents/            the agent-simulation engine + its API
    README.md          how the agents work: memory, reflection, planning, the tick loop
    config.py, llm.py, providers/ (ollama.py, claude.py)
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
| `history/eras.py`, `entities.py`, `events.py`, `grammar.py`, `names.py`, `architecture.py` | history | The procedural-history engine itself -- modeled on Jason Grinblat's GDC talk on Caves of Qud's mythic-biography generator: entities as mutable-property bags, events resolved by reading current state (not simulated causality), text produced by a real replacement grammar (`grammar.py`). All *content* lives in the matching `.yaml` file in `data/`; the `.py` file loads it and holds only behavior. See `history/README.md`. |
| `history/characters.py` | history | Present-day residents, each grounded in one real place's founder/domain/history, with a bio that includes physical appearance and wardrobe (so image generation has something to work from). Generated on demand from the UI ("+ New agent": preview, edit, save), not as part of city generation. |
| `history/summary.py` | history | One LLM call at the very end of a run: a short narrative summary of the city's history (the Inspector's overview). Falls back to a plain stats sentence with no LLM. |
| `history/generate.py` | history | `run_history()` (called by `jobs.py`) and a standalone CLI (`python3 -m history.generate --seed 42`) that does the same thing plus writes `history.json`/`characters.json`. |
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
