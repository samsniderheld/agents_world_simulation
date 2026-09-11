# The history generator

Procedurally generates a ~330-year history (1624 Dutch colonization → the
late 1950s) for a single NYC-inspired city: a cast of historical figures,
a catalog of places they found/destroy/rename/fight over, a map of the
resulting city, and a handful of present-day residents grounded in all of
it. Entry point: `generate.run_history()` (called by `jobs.py`'s
background thread; `python3 -m history.generate` runs the same thing as a
standalone CLI — see the project root [README.md](../README.md)).

The generation model is not a simulation with real causality. It's the
one Jason Grinblat described at GDC for *Caves of Qud*'s mythic-history
generator: events are picked largely at random, but *resolving* one reads
a figure's accumulated state (their rivals, allies, domain) and turns that
state into the event's stated "cause." State set by an earlier,
unrelated-seeming event becomes the rationalization a later one gives for
itself — the same trick behind the talk's own example of two cats and a
frog. Nothing here plans ahead or checks for narrative coherence; the
coherence is an illusion produced by always reading forward from what
already happened.

## The pieces

| Concept | What it is | Where |
|---|---|---|
| **Era** | One of 8 fixed named periods spanning 1624–1959, each with its own year range and a `description` used as color text. | `eras.py` / `data/eras.yaml` |
| **Figure** | A person: name, role (Merchant, Gang Boss, Reverend, ...), domain (a one/two-word thematic tag like "the harbor" or "iron"), birth/death year, and a mutable `properties` bag (`allies`, `rivals`, `reputation`, `founded_places`). | `entities.py` |
| **Place** | A location: name, type (Tavern, Shipyard, Tenement, ...), founding year/figure, current owner, `status` (active/destroyed/closed), and its own append-only `history` list of every event that touched it. | `entities.py` |
| **Event template** | A pool of ~15 kinds of thing that can happen (found a place, feud violence, scandal, rename, ...), each with a grammar for its Gospel text, an optional effect function that mutates a figure/place, and an optional precondition/place-filter gating when it's eligible. | `events.py` / `data/events.yaml` |
| **Grammar** | A tiny replacement-grammar engine: named symbols, each a list of weighted string rules; `{symbol}` recurses, `{context_key}` fills from the event's context dict. | `grammar.py` |
| **Gospel text** | The one sentence an event produces — the generator's only real "output" per event; everything else (JSON fields) is bookkeeping in service of producing more of these later. | — |

The 8 eras, in order (`data/eras.yaml`):

```
1624 ─┬─ New Amsterdam (Dutch Colonial)
1664 ─┤   New York (English Colonial)
1783 ─┤   Early Republic
1825 ─┤   Antebellum & Immigration Boom
1861 ─┤   Civil War & Gilded Age
1900 ─┤   Progressive Era & Tenement City
1917 ─┤   (no era covers 1917-1920 — the gap between Progressive and
      │    Prohibition roughly spans WWI)
1920 ─┤   Prohibition & Jazz Age
1933 ─┤   Depression, War & Postwar
1959 ─┴─
```

## Algorithm: `generate.generate()`

The whole engine hinges on one ordering trick, explained in the function's
own docstring: figures and their event *schedules* are created per-era
(in era order), but the events themselves are *resolved* in true
chronological order across the whole timeline. If they were resolved in
creation order instead, a figure from a later era could end up renaming a
place before an earlier era's figure had even founded it — the schedule
sort is what keeps a place's `history` reading as a real timeline.

```
Phase 1 — schedule (no Place is touched yet)
┌─────────────────────────────────────────────────────────────────┐
│ for each era, in era order:                                     │
│     for FIGURES_PER_ERA new figures:                            │
│         create a Figure (random role/domain/birth_year in era)  │
│         year = birth_year                                       │
│         for EVENTS_PER_FIGURE slots:                            │
│             year += random(1..6), clamped to MAX_YEAR           │
│             schedule.append((year, figure, era))                │
└─────────────────────────────────────────────────────────────────┘
                              │
                sort schedule by year  (creation order thrown away)
                              ▼
Phase 2 — resolve (Place state read + mutated here)
┌─────────────────────────────────────────────────────────────────┐
│ for (year, figure, era) in schedule, ascending:                 │
│     if not figure.alive: skip  (already died in an earlier slot)│
│     template = pick_event_template(figure, all_places)          │
│     gospel_text, place, is_new = resolve_event(...)             │
│     record the event; append it to place.history if any place   │
│                                                                   │
│ then, one final pass over every still-alive figure:              │
│     death_year = last_scheduled_year + random(1..10)             │
│     resolve_death(figure, death_year)  → one more Gospel line    │
└─────────────────────────────────────────────────────────────────┘
```

### Picking and resolving one event (`events.py`)

```
pick_event_template(figure, places)
   │
   ├─ filter EVENT_TEMPLATES to those whose precondition passes
   │     e.g. "expansion" requires has_founded_a_place(figure)
   ├─ for templates that require an *existing* place, also require
   │     at least one place matching their place_filter
   │     e.g. "rebuilt_place" only fires if a destroyed_place exists
   └─ rng.choice(eligible) — or "found_place" if nothing is eligible
                              (the one template with no preconditions,
                              guaranteeing every figure does *something*)

resolve_event(template, figure, places, era, year)
   │
   ├─ requires_place == "new"       → create_place(figure, era, year)
   ├─ requires_place == "existing"  → rng.choice(places matching filter)
   ├─ else                           → no place involved
   │
   ├─ extra = template.effects(figure, place, era, year, rng)
   │     mutates figure/place in place, e.g.:
   │       place_destroyed → place.status = "destroyed"
   │       alliance_formed → figure.properties["allies"].append(faction)
   │       feud_violence   → 12% chance figure also dies right here,
   │                          redirecting the Gospel text to a death line
   │
   └─ gospel_text = grammar.expand(template.grammar, "TEXT", context)
        then _maybe_flourish(): for a fixed subset of "notable" template
        ids, occasionally (LLM_FLOURISH_RATE) asks Ollama to rewrite the
        sentence more vividly, with every proper noun/fact pinned in the
        prompt so it can't invent or drop one — falls back to the plain
        grammar sentence on any failure or if Ollama is off.
```

### The causality trick — `_pick_cause`

This is the heart of the whole model. Several effect functions (place
destroyed, ownership change, scandal, political trouble, feud violence,
decline) need a `{cause}` slot for their Gospel sentence, and `_pick_cause`
answers it by reading the figure's *accumulated* state instead of
inventing something fresh:

```
_pick_cause(figure):
    roll = random()
    if figure has rivals and roll < 0.45:
        return "the persecution of {a rival}"
    elif figure has allies and roll < 0.75:
        return "a debt owed to {an ally}"
    else:
        return a generic, domain-flavored reason
```

A figure only *has* rivals/allies because some earlier, unrelated event
(`rivalry_formed`, `alliance_formed`) put one there. So a tavern burning
down in 1710 might be blamed on "the persecution of the Brewers' Guild" —
not because the generator planned a rivalry-driven arson plot, but because
a `rivalry_formed` event happened to that same figure a few scheduled
slots earlier, and `_pick_cause` picked it up mechanically. Every event
after that point can keep pointing back at it. This is exactly the "cats
and the frog" illusion the GDC talk describes: the appearance of a causal
throughline that the generator never actually modeled.

### Text generation — grammar, not LLM, by default

`grammar.expand()` is what actually turns a template + context dict into
a sentence: pick one weighted rule for a named symbol, then recursively
substitute any `{other_symbol}` refs and fill `{context_key}` refs
straight from the context (figure name, place name, year, era, ...). This
runs with Ollama completely offline — `config.LLM_FILL_NAMES` only ever
adds *variety* on top (better proper nouns via `names.py`, an occasional
vivid rewrite via `_maybe_flourish`), never removes the grammar fallback.
Every LLM call in this package follows that same shape: try it, validate
the reply loosely, fall back silently on any failure or timeout.

## Worked example: one event line, start to finish

Everything above, traced through one concrete Gospel line. Nothing here is
invented for illustration — every value comes from a real code path or a
real word list, just with the random rolls pinned so the trace is
followable. Assume `LLM_FILL_NAMES` is off, so every step is pure grammar
(a later note shows where an LLM flourish could still land on top).

**Setup — two events already resolved earlier in this figure's schedule:**

```
entities.new_figure("english_colonial", rng)
  role   = rng.choice(roles_for_era("english_colonial"))  → "Ship Captain"
  domain = rng.choice(DOMAINS)                             → "the harbor"
  name   = names.figure_name(...)  → grammar fallback: english given/surname
                                       lists → "Thomas Beekman"
  birth_year = 1698
→ Figure(id=fig_1, name="Thomas Beekman", role="Ship Captain",
         domain="the harbor", era_id="english_colonial", birth_year=1698,
         properties={allies: [], rivals: [], reputation: [], founded_places: []})

[1706] template = "found_place" (always eligible — no precondition)
  _create_place: place_type = rng.choice(place_types_for_era(...)) → "Shipyard/Dock/Warehouse"
                 naming_style["Shipyard/Dock/Warehouse"] = "firm"
                 → "Beekman & Sons" (founder_surname + " & Sons")
  → Place(id=place_1, name="Beekman & Sons", place_type="Shipyard/Dock/Warehouse",
          domain="the harbor" (inherited from the figure), founded_year=1706,
          founding_figure_id=fig_1, current_owner_figure_id=fig_1, status="active")
  fig_1.properties["founded_places"] = [place_1]
  Gospel: "Thomas Beekman opened the doors of Beekman & Sons in 1706, a
           shipyard that would carry the mark of the harbor for years to come."

[1715] template = "rivalry_formed" (requires_place: null — no place involved)
  _fx_rivalry_formed: faction = rng.choice(FACTIONS not already a rival) → "the harbor pilots"
  fig_1.properties["rivals"] = ["the harbor pilots"]
  Gospel: "Thomas Beekman made an enemy of the harbor pilots in 1715."
```

Nothing about these two events refers to each other. `rivalry_formed` never
mentions a place; `found_place` never mentions a rival. The only thing they
share is that both mutated the *same* `fig_1.properties` bag — which is
exactly what the next event reads.

**The event being diagrammed — year 1727:**

```
┌─ pick_event_template(fig_1, all_places) ──────────────────────────────┐
│ eligible = every template whose precondition passes and (if           │
│            requires_place == "existing") whose place_filter matches   │
│            at least one place                                         │
│ "place_destroyed": requires_place="existing", place_filter=           │
│   active_place → Beekman & Sons qualifies (status == "active")        │
│ rng.choice(eligible) → "place_destroyed"                               │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ resolve_event(template, fig_1, all_places, era, 1727, rng) ──────────┐
│ requires_place == "existing" → place = rng.choice(places matching     │
│                                  active_place)  →  Beekman & Sons      │
│                                                                         │
│ extra = _fx_place_destroyed(fig_1, place, era, 1727, rng):             │
│    disaster = rng.choice(DISASTERS)         → "fire"                  │
│    place.status = "destroyed"; place.closed_year = 1727    (mutation) │
│    cause = _pick_cause(fig_1, rng):                                    │
│        rivals = ["the harbor pilots"], allies = []                    │
│        roll = 0.30  (< 0.45)                                          │
│        → "the persecution of " + rng.choice(rivals)                   │
│        → "the persecution of the harbor pilots"        ◄── the 1715   │
│                                                              event,    │
│                                                              read back │
│    extra = {"disaster": "fire", "cause": "the persecution of the      │
│             harbor pilots"}                                            │
│                                                                         │
│ context = _build_context(fig_1, place, era, 1727, extra):             │
│    {figure: "Thomas Beekman", role: "Ship Captain", domain: "the      │
│     harbor", year: 1727, era: "New York (English Colonial)",          │
│     place: "Beekman & Sons", place_noun: "shipyard",                  │
│     disaster: "fire", cause: "the persecution of the harbor pilots"}  │
│                                                                         │
│ grammar.expand(template.grammar, "TEXT", context, rng):                │
│    rng.choice(12 weighted TEXT rules) →                                │
│    "{figure} watched {place} go down to {disaster} in {year}, and     │
│     blamed {cause}."                                                   │
│    → substitute every {token} from context                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
       "Thomas Beekman watched Beekman & Sons go down to fire in 1727,
        and blamed the persecution of the harbor pilots."
                              │
                              ▼
┌─ _maybe_flourish(text, "place_destroyed", rng) ───────────────────────┐
│ "place_destroyed" is in notable_template_ids (events.yaml) → eligible │
│ if rng.random() <= LLM_FLOURISH_RATE and llm.available():             │
│    ask Ollama to rewrite it more vividly, every name/date/fact pinned │
│    in the prompt so none can be invented or dropped, e.g.:            │
│    "Fire took Beekman & Sons in the winter of 1727, and more than a   │
│     few said the harbor pilots had finally settled their score with   │
│     Thomas Beekman."                                                  │
│ else (or on any failure/timeout): keep the plain grammar sentence     │
│    unchanged — this is the offline-safe default                       │
└─────────────────────────────────────────────────────────────────────┘
```

**What lands in the JSON, and what prints to the log** (`generate()`,
back in the main loop):

```python
event_record = {
    "id": "evt_84", "era_id": "english_colonial", "year": 1727,
    "template_id": "place_destroyed", "figure_id": "fig_1",
    "place_id": "place_1",
    "gospel_text": "Thomas Beekman watched Beekman & Sons go down to "
                   "fire in 1727, and blamed the persecution of the "
                   "harbor pilots.",
}
```
appended to both `all_events` and `place_1.history`, and printed/logged as:
```
[1727] (New York (English Colonial)) Thomas Beekman: Thomas Beekman watched
Beekman & Sons go down to fire in 1727, and blamed the persecution of the
harbor pilots.
```

From here, `place_1.status == "destroyed"` is exactly what a later
`rebuilt_place` event's `place_filter` would key off of, and this event's
own `figure_id`/`place_id` are what group it under the right figure/place
in the final JSON and (via `citymap.py`) locate it on the map. The one
thing this event did *not* need to know about — the 1715 rivalry — is the
one thing that made its `{cause}` feel motivated instead of arbitrary.

## After the event loop: map, characters, summary

`run_history()` runs three more steps after `generate()` returns, each
reading the finished figures/places/events but not feeding back into them:

```
run_history()
  │
  ├─ generate()                    → figures, places, events (above)
  │
  ├─ citymap.build_map(places, figures)
  │     groups places by the era of their founding figure, grows a
  │     domain-warped noise archipelago, carves era-band × west/east-column
  │     sections as neighborhoods, drops a numbered [N] label for every
  │     place — see "The map" below
  │
  ├─ characters.generate_characters(places, figures, count=10)
  │     for each of 10 residents: pick a place (weighted toward one with
  │     more recorded history), then either ask the LLM to invent someone
  │     grounded in that place's founder + a real anecdote from its
  │     history, or fall back to a template-driven bio from characters.yaml
  │
  └─ summary.generate_summary(figures, places, events, eras)
        one LLM call over the *entire* chronological event transcript,
        asked for a 3-5 paragraph narrative arc — the one point in the
        whole run that looks at everything at once instead of one
        figure/place/event at a time. Falls back to a one-sentence stats
        summary offline.
```

## The map (`citymap.py`)

Also generative, not templated, using an unrelated technique (fractal
noise, not a replacement grammar) for a different reason: geography needs
to look organic, not grammatically rich.

```
_generate_island_mask()
  1. two Perlin noise fields: one for elevation, one to "warp" the
     coordinates the elevation field is sampled at (domain warping —
     what bends coastlines into hooks/spits instead of blobby contours)
  2. elevation = fractal_noise(warped x, y) − center_bias · distanceᵖ
     (a soft pull toward the map center, not a hard boundary)
  3. threshold at sea_level → land/water mask
  4. connected-component analysis:
       - auto-adjust sea_level until the largest landmass clears a floor
         (MAIN_ISLAND_MIN_FRACTION) without flooding the whole map
       - cull any component smaller than MIN_ISLAND_DOTS as a noise speck
  5. ~most runs (EDGE_LANDMASS_CHANCE) also get a secondary landmass
     hugging the west or east edge, elevation-boosted from a center placed
     off-frame — reads as "Brooklyn" continuing past the frame

texture + rasterize
  dot_grid(): sparser dots for water than land (LAND_DENSITY/WATER_DENSITY)
  → packed into Unicode braille characters (2×4 dots per glyph) for the
    CLI's plain-text map

neighborhoods
  each era gets a horizontal band (newest era = top); each band is split
  into NEIGHBORHOOD_COLUMNS (west/east); band and column boundaries are
  themselves noise-wobbled curves (_wavy_boundaries), not straight cuts,
  clamped so they never cross. Every (era × column) cell is one
  neighborhood: named by the LLM from a sample of its places (or a plain
  "{column} {era} Quarter" fallback), given a golden-ratio-stepped hue so
  adjacent neighborhoods never look near-identical, and every place
  founded in that era gets shuffled into a column and stamped with a
  numbered [N] label on its own land.
```

`build_map()` returns two different shapes depending on mode:

- **Procedural (default)**: `{text, neighborhoods, graphic}` — `graphic`
  carries the raw land mask, boundary curves, and marker positions the
  web UI's interactive canvas (`static/js/citymap.js`) draws from at full
  resolution; `text` is the same data already rasterized to braille for
  the CLI.
- **LLM-drawn (`llm_map=True`, opt-in)**: the LLM freehand-draws the whole
  map as ASCII art instead, validated (every place's `[N]` label must
  actually appear in the reply, checked over up to `LLM_MAP_MAX_RETRIES`
  attempts with the specific problem fed back as retry feedback) before
  being accepted; falls back to the procedural map on repeated failure.
  Returns `{text, body, caption, neighborhoods: []}` — no `graphic` key,
  which is exactly what the frontend checks to tell the two modes apart,
  since freeform ASCII art has no structured grid for a canvas to draw.

## Everything is tunable, not hardcoded

Every knob mentioned above — figures/events per era, the LLM flourish
rate, every map-noise parameter, chat-model tiers by available RAM — lives
in `data/config.yaml`, loaded once by `config.py`. All *content* — era
definitions, domains/factions/roles/place-types-and-which-eras-they're
valid-in, name word lists per era, event templates and their word pools,
character bio templates — lives in the matching `data/*.yaml` file, not in
the `.py` files, which hold only behavior (see each module's docstring for
exactly which YAML backs it).
