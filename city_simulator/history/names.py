"""Proper-noun generation: person names and place names.

Pure-grammar word lists (era-flavored, the theme's `names` section) are the base -- this
must keep working with Ollama offline. When config.LLM_FILL_NAMES is on and
Ollama is reachable (llm.available()), we ask the local model for a name
instead, since it's cheap and produces far more varied, specific results
than a fixed word list ever will; any failure (timeout, bad output) falls
straight back to the grammar with no visible error.
"""

import random

import theme

from . import config
from . import llm
from .eras import eras_by_id


def _data() -> dict:
    return theme.current()["names"]


def _names_for_era(era_id: str):
    n = _data()
    groups = n["name_groups"]
    group = groups.get(n.get("era_name_groups", {}).get(era_id), groups[n["default_name_group"]])
    return group["given"], group["surname"]


def _grammar_figure_name(era_id: str, rng: random.Random) -> str:
    givens, surnames = _names_for_era(era_id)
    return f"{rng.choice(givens)} {rng.choice(surnames)}"


def _grammar_place_name(place_type: str, domain: str, founder_surname: str, rng: random.Random) -> str:
    """The theme's naming pattern for this place type, slots filled left to
    right: {surname}, {domain_title}, {place_type_short}, {number},
    {call_letters}, or a word list from place_name_words (random pick)."""
    n = _data()
    style = n.get("naming_style", {}).get(place_type, n["default_naming_style"])
    pattern = n["naming_patterns"][style]
    words = n.get("place_name_words") or {}

    def value(slot: str) -> str:
        if slot == "surname":
            return founder_surname
        if slot == "domain_title":
            # domain may itself start with "the" (e.g. "the vote") -- strip it
            # before title-casing so this doesn't produce "The The Vote Sentinel".
            return (domain[4:] if domain.lower().startswith("the ") else domain).title()
        if slot == "place_type_short":
            return place_type.split("/")[0]
        if slot == "number":
            return str(rng.randint(1, 400))
        if slot == "call_letters":
            return "".join(c for c in founder_surname.upper() if c.isalpha())[:3].ljust(3, "X")
        return rng.choice(words[slot])
    return theme.fill(pattern, {s: value(s) for s in _ordered_slots(pattern)})


def _ordered_slots(pattern: str) -> list:
    """Slots in order of appearance, so random picks happen left to right."""
    out = []
    for slot in theme._SLOT.findall(pattern):
        if slot not in out:
            out.append(slot)
    return out


def figure_name(era_id: str, role: str, rng: random.Random) -> str:
    if config.LLM_FILL_NAMES and llm.available():
        era = eras_by_id().get(era_id)
        try:
            t = theme.current()
            prompt = (t.prompt("history.figure_name", role=role, era_name=era.name, era_start=era.start_year,
                               era_end=era.end_year) if era else
                      t.prompt("history.figure_name_no_era", role=role))
            name = llm.complete(prompt, temperature=0.9).strip().strip('"').strip(".")
            if name and "\n" not in name and 3 <= len(name) <= 50:
                return name
        except Exception:
            pass
    return _grammar_figure_name(era_id, rng)


def place_name(place_type: str, domain: str, founder_surname: str, era_id: str, rng: random.Random) -> str:
    if config.LLM_FILL_NAMES and llm.available():
        era = eras_by_id().get(era_id)
        try:
            from .eras import all_eras
            prompt = theme.current().prompt(
                "history.place_name", place_type=place_type, surname=founder_surname, domain=domain,
                year=era.start_year if era else all_eras()[0].start_year)
            name = llm.complete(prompt, temperature=0.95).strip().strip('"').strip(".")
            if name and "\n" not in name and 2 <= len(name) <= 60:
                return name
        except Exception:
            pass
    return _grammar_place_name(place_type, domain, founder_surname, rng)
