"""Generates present-day (c. 1959) residents of the city, each grounded in
a specific piece of the generated history -- a place, its domain, its
founder, and a real recorded incident there -- rather than being generic
NPCs. The LLM is genuinely better at weaving specific facts into a natural
bio than a template is, so it's the primary path here (unlike the grammar-
first approach for the bulk of history generation); a plain fallback (its
sentence pools live in characters.yaml) still keeps this working with
Ollama offline.
"""

import random
from pathlib import Path

import yaml

from . import config
from . import entities
from . import llm
from . import names

_YAML_PATH = Path(__file__).parent / "data" / "characters.yaml"

with open(_YAML_PATH) as _f:
    _RAW = yaml.safe_load(_f)

_RELATIONSHIP_HINTS = _RAW["relationship_hints"]  # {"active": [...], "gone": [...]}
_BIO_TEMPLATES = _RAW["bio_templates"]             # {"active_with_founder": [...], ...}


def _pick_grounding(places: list, figures: list, rng: random.Random, exclude: set,
                     force_place_id: str = None) -> dict:
    figures_by_id = {f.id: f for f in figures}
    if force_place_id:
        place = next((p for p in places if p.id == force_place_id), None)
        if place is None:
            raise ValueError(f"unknown place: {force_place_id!r}")
    else:
        candidates = [p for p in places if p.id not in exclude] or list(places)
        # Favor places with a richer recorded history -- more for a bio to draw on.
        weights = [len(p.history) + 1 for p in candidates]
        place = rng.choices(candidates, weights=weights, k=1)[0]
    founder = figures_by_id.get(place.founding_figure_id)
    anecdote = rng.choice(place.history) if place.history else None
    hints = _RELATIONSHIP_HINTS["active"] if place.status == "active" else _RELATIONSHIP_HINTS["gone"]
    return {
        "place": place, "founder": founder, "anecdote": anecdote,
        "relationship": rng.choice(hints),
    }


def _llm_character(grounding: dict, occupation: str = None, sex: str = None):
    place, founder, anecdote = grounding["place"], grounding["founder"], grounding["anecdote"]
    place_noun = entities.PLACE_TYPE_NOUN.get(place.place_type, place.place_type.lower())
    lines = [
        f"Place: {place.name}, a {place_noun}, founded {place.founded_year}, "
        f"thematically associated with \"{place.domain}\". Current status: {place.status}.",
    ]
    if founder:
        lines.append(f"Founded by: {founder.name}, a {founder.role.lower()}.")
    if anecdote:
        lines.append(f"A recorded incident there: {anecdote['gospel_text']}")
    lines.append(f"Write this character as {grounding['relationship']}.")
    if occupation:
        lines.append(f"This character's occupation must be: {occupation}.")
    if sex:
        lines.append(f"This character is {sex}.")

    constraint = ""
    if occupation:
        constraint += f", whose occupation is exactly \"{occupation}\""
    if sex:
        constraint += f" and who is {sex}"

    prompt = (
        "You are writing a short character dossier for a resident of an alternate-history "
        "New York City, living around 1959, in a film noir style world. "
        "the character should feel like an archetype from those types of movies."
        "Here is a real piece of that city's generated "
        "history:\n\n" + "\n".join(lines) +
        f"\n\nInvent ONE person deeply connected to this specific history{constraint}. "
        "Reply in exactly this format, nothing else:\n"
        "NAME: <full name>\n"
        "AGE: <integer between 20 and 75>\n"
        "OCCUPATION: <short phrase>\n"
        "QUIRK: <one distinctive habit or trait, a few words>\n"
        "BIO: <3-4 sentences, third person, naturally weaving in the place name, its domain, "
        "and the historical detail above -- specific to this history, not generic>"
    )
    reply = llm.complete(prompt, temperature=0.95)

    fields = {}
    for line in reply.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().upper()
        if key in ("NAME", "AGE", "OCCUPATION", "QUIRK", "BIO"):
            fields[key] = value.strip()
    if not all(k in fields for k in ("NAME", "AGE", "OCCUPATION", "BIO")):
        return None

    digits = "".join(c for c in fields["AGE"] if c.isdigit())
    age = max(18, min(90, int(digits))) if digits else 40

    return {
        "id": entities.new_id("char_"),
        "name": fields["NAME"], "age": age,
        # A given occupation is used verbatim rather than trusting the
        # LLM's own OCCUPATION line -- it's a hard constraint, not a
        # suggestion, and the prompt already steered the bio to match it.
        "occupation": occupation or fields["OCCUPATION"],
        "quirk": fields.get("QUIRK", ""), "bio": fields["BIO"],
        "place_id": place.id, "place_name": place.name,
        "founder_id": founder.id if founder else None,
    }


def _fallback_character(grounding: dict, rng: random.Random,
                         occupation: str = None, sex: str = None) -> dict:
    place, founder = grounding["place"], grounding["founder"]
    if not occupation:
        occupation = f"Keeper of {place.name}" if place.status == "active" else f"Historian of {place.name}"
    # `sex` isn't honored here -- names.yaml's word lists aren't split by
    # gender (a pre-existing limitation this grammar fallback shares with
    # historical-figure naming), so there's no signal to bias the name
    # pick on. Only the LLM path above can actually act on it.
    name = names.figure_name("depression_war", occupation, rng)

    # Separate template pools per (still-standing vs. gone) x (has a known
    # founder to reference or not) -- each a complete, self-contained
    # sentence, so a "no blood relation" hint can never get a contradictory
    # "descended from" clause spliced into it, and {place} never dangles
    # awkwardly at a sentence's end.
    if place.status == "active":
        pool = _BIO_TEMPLATES["active_with_founder"] if founder else _BIO_TEMPLATES["active_no_founder"]
    else:
        pool = _BIO_TEMPLATES["gone_with_founder"] if founder else _BIO_TEMPLATES["gone_no_founder"]
    relationship_sentence = rng.choice(pool).format(
        name=name, place=place.name, founder=founder.name if founder else "",
    )

    place_noun = entities.PLACE_TYPE_NOUN.get(place.place_type, place.place_type.lower())
    bio = (
        f"{relationship_sentence} {place.name} is the old {place_noun} "
        f"steeped in {place.domain}. Ask {name.split()[0]} about it and they will talk your ear off."
    )
    return {
        "id": entities.new_id("char_"),
        "name": name, "age": rng.randint(24, 72), "occupation": occupation,
        "quirk": f"can't stop talking about {place.domain}", "bio": bio,
        "place_id": place.id, "place_name": place.name,
        "founder_id": founder.id if founder else None,
    }


def generate_characters(places: list, figures: list, count: int = 10, seed=None) -> list:
    """10 (by default) present-day residents, each grounded in a different
    place's history where possible."""
    rng = random.Random(seed)
    used_place_ids = set()
    out = []
    for _ in range(count):
        if not places:
            break
        grounding = _pick_grounding(places, figures, rng, used_place_ids)
        used_place_ids.add(grounding["place"].id)

        char = None
        if config.LLM_FILL_NAMES and llm.available():
            try:
                char = _llm_character(grounding)
            except Exception:
                char = None
        if char is None:
            char = _fallback_character(grounding, rng)
        out.append(char)
    return out


def generate_one(places: list, figures: list, exclude_place_ids: set = None,
                  force_place_id: str = None, occupation: str = None, sex: str = None,
                  seed=None) -> dict:
    """The single-character equivalent of one generate_characters() loop
    iteration -- for the web app's on-demand "Generate Character" flow
    (history/routes.py's POST /api/history/characters/preview), rather
    than history generation's own fixed batch. `force_place_id`, if given,
    grounds the new character at that exact place instead of the usual
    weighted-random pick; raises ValueError if it doesn't resolve, so the
    route layer can turn that into a clean 400 rather than silently
    falling back to a random place. `occupation`/`sex`, if given, are
    hard constraints handed to the LLM path (and `occupation` alone is
    still honored verbatim by the no-LLM fallback, which has no way to
    act on `sex` -- see _fallback_character's docstring)."""
    if not places:
        raise ValueError("no places to ground a character in")
    rng = random.Random(seed)
    grounding = _pick_grounding(places, figures, rng, exclude_place_ids or set(),
                                 force_place_id=force_place_id)

    char = None
    if config.LLM_FILL_NAMES and llm.available():
        try:
            char = _llm_character(grounding, occupation=occupation, sex=sex)
        except Exception:
            char = None
    if char is None:
        char = _fallback_character(grounding, rng, occupation=occupation, sex=sex)
    return char
