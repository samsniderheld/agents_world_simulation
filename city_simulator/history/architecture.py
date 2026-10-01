"""One-sentence architecture description for a Place, generated once when
it's founded (and regenerated if it's ever rebuilt -- see events.py's
_fx_rebuilt_place, since a building razed in one era and rebuilt decades
later would genuinely look different).

Crosses two independent axes, both from the current theme's `architecture`
section (theme.py):
era (a real period style -- Dutch Colonial stepped gables through postwar
Streamline Moderne -- with its own material/feature/adjective word pools)
and place_type (its place_scale: what kind and scale
of structure this actually is, e.g. "an imposing counting house" vs. "a
cramped multi-family tenement"), so two places founded the same year in
different lines of work don't read as the same building in different
paint.

LLM-primary, like names.py/characters.py -- real period-appropriate detail
reads far better than a fixed grammar could produce -- with a grammar
fallback assembled from the same word pools so this keeps working with
Ollama offline.
"""

import random

import theme

from . import config
from . import entities
from . import llm


def _data() -> dict:
    return theme.current()["architecture"]   # eras: era_id -> {style, materials, ...}; place_scale


def _grammar_description(place_type: str, era_id: str, rng: random.Random) -> str:
    data = _data()
    style = data["eras"][era_id]
    scale = data["place_scale"].get(place_type, "a building")
    adjective = rng.choice(style["adjectives"])
    feature = rng.choice(style["features"])
    t = theme.current()
    # Landscape types (a park) have no "building" to describe.
    if place_type in (data.get("landscape_place_types") or []):
        return t.prompt("history.architecture_fallback_landscape", scale=scale.capitalize(), adjective=adjective,
                        style=style["style"], feature=feature)
    material = rng.choice(style["materials"])
    return t.prompt("history.architecture_fallback_building", scale=scale.capitalize(), adjective=adjective,
                    material=material, feature=feature)


def _llm_description(place_type: str, era, rng: random.Random) -> str:
    style = _data()["eras"][era.id]
    place_noun = entities.place_type_noun(place_type)
    prompt = theme.current().prompt("history.architecture", place_noun=place_noun, era_name=era.name,
                                    era_start=era.start_year, era_end=era.end_year, style=style["style"])
    text = llm.complete(prompt, temperature=0.9).strip().strip('"')
    if text and "\n" not in text and 15 <= len(text) <= 400:
        return text
    return None


def describe(place_type: str, era, rng: random.Random) -> str:
    """era is an eras.Era (needs .id/.name/.start_year/.end_year for the
    LLM prompt; the grammar fallback only needs era.id)."""
    if config.LLM_FILL_NAMES and llm.available():
        try:
            described = _llm_description(place_type, era, rng)
            if described:
                return described
        except Exception:
            pass
    return _grammar_description(place_type, era.id, rng)
