# history simulator

A procedural history generator for a single NYC-inspired city, 1624 (Dutch
colonization) through the late 1950s. It produces a catalog of historical
**places** — taverns, markets, churches, shipyards, tenements, theaters —
each carrying a full, internally-consistent chronological backstory, meant
to be reused later by some other project (a game, a story tool, whatever).

The model is lifted directly from Jason Grinblat's GDC talk on how
[Caves of Qud](https://www.cavesofqud.com/) procedurally generates its
mythic-biography history: historical **entities** (here, people and places)
are bags of mutable properties; historical **events** are chosen from a
template pool largely at random, but *resolving* one — picking a cause, an
outcome, who's involved — reads the entities' current state rather than
simulating any real causality; a **replacement grammar** turns each
resolved event into prose, parameterized by that state, so the same
template never reads the same way twice; and a central figure's one
persistent thematic **domain** (Qud's ice/fire/scholarship) colors their
events' imagery and acts as narrative glue across an otherwise
causally-disconnected string of events.

It's deliberately grammar-first, not LLM-first: the whole system produces
complete, readable output with Ollama switched off (`--no-llm`). The local
model is used narrowly — proper nouns, an optional prose flourish on
dramatic events, neighborhood names for the map, and the present-day
character bios — every one of those paths has a plain fallback.

## How it works

```text
generate.py
  |
  v
PHASE 1: Schedule  (every era, in order)
  |
  |-- spawn FIGURES_PER_ERA new Figures (name, role, domain, birth year --
  |     all era-appropriate; see entities.ROLES / entities.DOMAINS)
  |-- for each Figure, walk their life forward from birth_year in random
  |     1-6 year steps, EVENTS_PER_FIGURE times (capped at config.MAX_YEAR)
  |     -- this only schedules *when* something happens, not what
  v
PHASE 2: Resolve  (every scheduled slot, sorted into true chronological
  |                order across ALL eras -- see generate.py's docstring for
  |                why this has to happen in real year order, not
  |                per-figure creation order: two figures born in the same
  |                era have independent random birth years, and event
  |                resolution reads/writes Place state, so resolving out
  |                of order corrupts a place's history -- e.g. a "renamed"
  |                event citing a name that hasn't been set yet)
  |
  |-- events.pick_event_template()   mostly-random choice from the pool,
  |                                    filtered to what's currently possible
  |                                    (can't rebuild a place that isn't
  |                                    destroyed, etc.)
  |-- events.resolve_event()          reads Figure/Place state to pick a
  |     |                             cause/outcome (see events._pick_cause,
  |     |                             the direct analog of the talk's
  |     |                             "persecution of {faction}" example),
  |     |                             mutates that state, and expands the
  |     |                             template's grammar into a Gospel
  |     v
  |   grammar.expand()                recursive {symbol} substitution +
  |                                     direct {context_key} fills
  v
PHASE 3: Deaths  (every Figure still alive) -- doesn't touch Place state,
  |                so safe to resolve in any order
  v
citymap.build_map()      an ASCII map of every Place, clustered by era into
  |                        a south-to-north silhouette (oldest = the
  |                        Battery, newest = uptown), with water, real
  |                        bridges gated by their actual opening year, and
  |                        LLM-named neighborhoods
  v
characters.generate_characters()   10 present-day (c. 1959) residents, each
  |                                  grounded in a specific Place's history
  |                                  -- its founder, its domain, a real
  |                                  recorded incident there
  v
history.json / map.txt / characters.json  -->  server.py + index.html
```

## Setup

1. (Optional) Install Ollama and pull a chat model — everything still works
   without this via `--no-llm`, just with plainer names and prose:
   ```bash
   brew install ollama
   ollama serve &
   ollama pull llama3.1:8b   # config.py auto-picks a model sized to your
                              # hardware; see config._CHAT_MODEL_TIERS
   ```
2. Install Python deps (Python 3.9+; there's a shared `.venv` one level up
   in this repo):
   ```bash
   python3 -m venv ../.venv && source ../.venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run it:
   ```bash
   python3 generate.py
   ```
   By default this generates a full history, prints the map and the ten
   residents to the console, writes `history.json` / `map.txt` /
   `characters.json`, then starts a local web server and opens a browser to
   view it all. Pass `--no-serve` to skip the last step.

Useful flags:
```bash
python3 generate.py --seed 42                    # reproducible run
python3 generate.py --no-llm                     # skip Ollama entirely
python3 generate.py --figures-per-era 6 --events-per-figure 12   # a denser history
python3 generate.py --characters 20              # more present-day residents
python3 generate.py --out my_history.json --map-out "" --characters-out ""  # blank path = skip that file
```

Re-view an already-generated `history.json` without regenerating:
```bash
python3 server.py
```

## Architecture

| File | Talk concept | What it does |
|---|---|---|
| `grammar.py` | Replacement grammars | The actual engine: `expand()` recursively picks a weighted rule for a symbol and substitutes `{other_symbols}` (recursive) and `{context_key}`s (direct) — not simulated with plain f-strings. |
| `eras.py` | Periods | Eight real NYC eras (Dutch Colonial → Depression/Postwar) spanning 1624-1959, each spawning its own Figures. |
| `entities.py` | Entities | `Figure` / `Place` dataclasses, plus the era-gated `ROLES` / `PLACE_TYPES` pools and the `DOMAINS` / `FACTIONS` lists (Qud's ice/fire domains and frogs/cats factions, respectively). |
| `events.py` | Events + causality | ~15 event templates (found a place, destroyed, renamed, rivalry formed, ...) and the resolution logic — `_pick_cause()` is the direct analog of the talk's "persecution of {faction}" example: look at state first, only fall back to a generic domain-flavored reason if nothing usable exists yet. |
| `names.py` | — (not in the talk) | Proper-noun generation for people and places: LLM-first, era-flavored word-list grammar fallback. |
| `generate.py` | The whole loop | Schedules every figure's life events, resolves them in true chronological order (see "How it works" above for why that matters), handles deaths, and serializes everything. |
| `citymap.py` | — (not in the talk) | The ASCII map: Python computes every coordinate and draws the grid (always aligned, regardless of place count); the LLM only names neighborhoods and writes the caption. |
| `characters.py` | — (not in the talk) | 10 present-day residents, each grounded in one Place's actual founder/domain/history rather than being generic. |
| `hardware.py` / `llm.py` / `config.py` | — | Same pattern as `agent_simulator`'s: hardware-tiered local model selection, a thin Ollama chat wrapper (no embeddings here — no memory stream to score). |
| `server.py` / `index.html` | — | A static viewer: serves `history.json` and renders it as eras → founded places (expandable full history) → present-day residents, styled as an archival document rather than reusing `agent_simulator`'s console look. |

## Output format (`history.json`)

Flat, id-cross-referenced lists — `eras`, `figures`, `places` (each with a
chronological `history` array of every event that touched it), `events`,
plus `map` (the same text as `map.txt`) and `characters`. See
`generate.py`'s `to_json()` for the exact shape.

## Deliberate simplifications (vs. a full simulation)

- **No real causality.** Exactly as the talk describes its own system: an
  event is picked at random, and its "cause" is a rationalization decided
  *after the fact* by reading current state — not a simulated consequence
  of anything.
- **A figure's era only loosely bounds their story.** Life events aren't
  clamped to their birth era's year range (a person born late in one era
  naturally lives into the next); only `config.MAX_YEAR` is a hard ceiling.
- **No Items/relics** as their own entity type (Qud has named artifacts
  like "Frost, Cat's Friend") — out of scope for a first pass; Places are
  the deliverable here.
- **The map's geography is stylized, not simulated.** Era index stands in
  for south-to-north position; the island silhouette (`ISLAND_COLS_PROFILE`
  in `citymap.py`) and the bridge list are both hand-picked, not derived
  from anything in the generated data.

## Extending

- Add more event templates to `events.EVENT_TEMPLATES` — the pattern
  (grammar + an effects function that reads/writes state) is the same
  throughout.
- Add an Item/relic entity type, following Place's shape, for named
  artifacts tied to notable events.
- `characters.py`'s grounding logic (pick a place, its founder, an
  anecdote) generalizes easily to grounding other kinds of generated
  content in this same history.
