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
