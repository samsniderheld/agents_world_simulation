"""One-sentence architecture description for a Place, generated once when
it's founded (and regenerated if it's ever rebuilt -- see events.py's
_fx_rebuilt_place, since a building razed in one era and rebuilt decades
later would genuinely look different).

Crosses two independent axes, both loaded from data/architecture.yaml:
era (a real period style -- Dutch Colonial stepped gables through postwar
Streamline Moderne -- with its own material/feature/adjective word pools)
and place_type (data/architecture.yaml's place_scale: what kind and scale
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
from pathlib import Path

import yaml

from . import config
from . import entities
from . import llm

_YAML_PATH = Path(__file__).parent / "data" / "architecture.yaml"

with open(_YAML_PATH) as _f:
    _RAW = yaml.safe_load(_f)

_ERA_STYLES = _RAW["eras"]          # era_id -> {style, materials, features, adjectives}
_PLACE_SCALE = _RAW["place_scale"]  # place_type -> short descriptive noun phrase

_LANDSCAPE_TYPE = "Park/Public Square"  # the one place_type with no "building" to describe


def _grammar_description(place_type: str, era_id: str, rng: random.Random) -> str:
    style = _ERA_STYLES[era_id]
    scale = _PLACE_SCALE.get(place_type, "a building")
    adjective = rng.choice(style["adjectives"])
    feature = rng.choice(style["features"])
    if place_type == _LANDSCAPE_TYPE:
        return f"{scale.capitalize()}, laid out in a {adjective} {style['style']} taste, with {feature}."
    material = rng.choice(style["materials"])
    return f"{scale.capitalize()}, {adjective} and built of {material}, notable for {feature}."


def _llm_description(place_type: str, era, rng: random.Random) -> str:
    style = _ERA_STYLES[era.id]
    place_noun = entities.PLACE_TYPE_NOUN.get(place_type, place_type.lower())
    prompt = (
        f"Describe, in exactly one vivid sentence, the architecture and "
        f"physical appearance of a {place_noun} in New York City, built "
        f"during the \"{era.name}\" era ({era.start_year}-{era.end_year}). "
        f"The dominant architectural style of that era is {style['style']}. "
        f"Reference real, period-appropriate materials and details, sized "
        f"appropriately for a {place_noun} specifically -- not a mansion or "
        f"a monument, unless that's genuinely what a {place_noun} would be. "
        f"Reply with ONLY the sentence, no preamble."
    )
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
