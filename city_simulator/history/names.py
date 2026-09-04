"""Proper-noun generation: person names and place names.

Pure-grammar word lists (era-flavored, in names.yaml) are the base -- this
must keep working with Ollama offline. When config.LLM_FILL_NAMES is on and
Ollama is reachable (llm.available()), we ask the local model for a name
instead, since it's cheap and produces far more varied, specific results
than a fixed word list ever will; any failure (timeout, bad output) falls
straight back to the grammar with no visible error.
"""

import random
from pathlib import Path

import yaml

from . import config
from . import llm
from .eras import ERAS_BY_ID

_YAML_PATH = Path(__file__).parent / "data" / "names.yaml"

with open(_YAML_PATH) as _f:
    _RAW = yaml.safe_load(_f)

_NAME_GROUPS = _RAW["name_groups"]
_ERA_NAME_GROUPS = _RAW["era_name_groups"]
_DEFAULT_NAME_GROUP = "english"

_WORDS = _RAW["place_name_words"]
_ADJECTIVES = _WORDS["adjectives"]
_ANIMALS = _WORDS["animals"]
_SAINTS_VIRTUES = _WORDS["saints_virtues"]
_PRESS_WORDS = _WORDS["press_words"]
_STREETS = _WORDS["streets"]
_PRODUCTS = _WORDS["products"]

_NAMING_STYLE = _RAW["naming_style"]


def _names_for_era(era_id: str):
    group = _NAME_GROUPS.get(_ERA_NAME_GROUPS.get(era_id), _NAME_GROUPS[_DEFAULT_NAME_GROUP])
    return group["given"], group["surname"]


def _grammar_figure_name(era_id: str, rng: random.Random) -> str:
    givens, surnames = _names_for_era(era_id)
    return f"{rng.choice(givens)} {rng.choice(surnames)}"


def _grammar_place_name(place_type: str, domain: str, founder_surname: str, rng: random.Random) -> str:
    style = _NAMING_STYLE.get(place_type, "surname_possessive")
    if style == "tavern":
        return f"The {rng.choice(_ADJECTIVES)} {rng.choice(_ANIMALS)}"
    if style == "firm":
        return f"{founder_surname} & Sons"
    if style == "works":
        return f"{founder_surname} {rng.choice(_PRODUCTS)} Works"
    if style == "civic":
        return f"{rng.choice(_SAINTS_VIRTUES)}" if "Church" in place_type else f"{founder_surname} {place_type.split('/')[0]}"
    if style == "press":
        # domain may itself start with "the" (e.g. "the vote") -- strip it
        # before title-casing so this doesn't produce "The The Vote Sentinel".
        domain_word = domain[4:] if domain.lower().startswith("the ") else domain
        return f"The {domain_word.title()} {rng.choice(_PRESS_WORDS)}"
    if style == "address":
        return f"{rng.randint(1, 400)} {rng.choice(_STREETS)}"
    return f"{founder_surname}'s"


def figure_name(era_id: str, role: str, rng: random.Random) -> str:
    if config.LLM_FILL_NAMES and llm.available():
        era = ERAS_BY_ID.get(era_id)
        try:
            prompt = (
                f"Give one plausible full person name (first and last) for a {role} "
                f"living in New York City during {era.name if era else era_id} "
                f"(roughly {era.start_year}-{era.end_year})." if era else
                f"Give one plausible full person name for a {role} in old New York City."
            )
            prompt += " Reply with ONLY the name, nothing else -- no titles, no explanation."
            name = llm.complete(prompt, temperature=0.9).strip().strip('"').strip(".")
            if name and "\n" not in name and 3 <= len(name) <= 50:
                return name
        except Exception:
            pass
    return _grammar_figure_name(era_id, rng)


def place_name(place_type: str, domain: str, founder_surname: str, era_id: str, rng: random.Random) -> str:
    if config.LLM_FILL_NAMES and llm.available():
        era = ERAS_BY_ID.get(era_id)
        try:
            prompt = (
                f"Give one short, period-appropriate business/place name for a "
                f"{place_type} in New York City around {era.start_year if era else '1800'}, "
                f"founded by someone surnamed {founder_surname}, thematically associated "
                f"with \"{domain}\". Reply with ONLY the name, nothing else."
            )
            name = llm.complete(prompt, temperature=0.95).strip().strip('"').strip(".")
            if name and "\n" not in name and 2 <= len(name) <= 60:
                return name
        except Exception:
            pass
    return _grammar_place_name(place_type, domain, founder_surname, rng)
