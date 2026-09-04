"""Event templates and resolution.

This is the core of the model the talk describes: an event is chosen from
the pool below largely at random (pick_event_template), but *resolving* it
-- deciding a cause, an outcome, who's involved -- reads the figure's
current state (rivals, allies, domain) rather than any real causal
simulation. The cause is a rationalization mediated by that state, exactly
as the talk describes its cats/frogs example: state set by an earlier event
becomes the "reason" a later, otherwise-unrelated event gives for itself.

The templates themselves (grammar text, word-list content like disasters/
scandal tags/political outcomes) live in events.yaml; this module holds the
actual behavior -- the effects/place_filter/precondition functions each
template's YAML entry references by name (see _EFFECTS/_PLACE_FILTERS/
_PRECONDITIONS and _load_template below).

Runtime template shape (what _load_template produces from one YAML entry):
  id             unique string
  requires_place "new" | "existing" | None
  place_filter   optional (place, figure) -> bool, only for "existing"
  precondition   optional (figure, places) -> bool, gates whether this
                 template is even eligible this turn
  grammar        dict for grammar.expand(); must have a "TEXT" symbol, may
                 have others (including alternate text symbols an effects
                 function can redirect to via the special "_text_symbol"
                 key -- see feud_violence's death branch below)
  effects        (figure, place, era, year, rng) -> dict of extra context
                 slots for the Gospel text; mutates figure/place in place
"""

import random
from pathlib import Path

import yaml

from . import config
from . import entities
from . import grammar
from . import llm
from . import names

_YAML_PATH = Path(__file__).parent / "data" / "events.yaml"

with open(_YAML_PATH) as _f:
    _RAW = yaml.safe_load(_f)

_GENERIC_CAUSES = _RAW["generic_causes"]
_DISASTERS = _RAW["disasters"]
_SCANDAL_TAGS = _RAW["scandal_tags"]
_POLITICAL_OUTCOMES = _RAW["political_outcomes"]
_NOTABLE_TEMPLATE_IDS = set(_RAW["notable_template_ids"])


def _pick_cause(figure: "entities.Figure", rng: random.Random) -> str:
    """The talk's central causality trick: look at state first, and only
    fall back to a generic (but still domain-flavored) reason if there's
    nothing usable in the figure's rivals/allies yet."""
    rivals = figure.properties.get("rivals", [])
    allies = figure.properties.get("allies", [])
    roll = rng.random()
    if rivals and roll < 0.45:
        return f"the persecution of {rng.choice(rivals)}"
    if allies and roll < 0.75:
        return f"a debt owed to {rng.choice(allies)}"
    return rng.choice(_GENERIC_CAUSES).format(domain=figure.domain)


def _create_place(figure: "entities.Figure", era, year: int, rng: random.Random) -> "entities.Place":
    place_type = rng.choice(entities.place_types_for_era(era.id))
    surname = figure.name.split()[-1]
    name = names.place_name(place_type, figure.domain, surname, era.id, rng)
    return entities.new_place(figure, place_type, name, year)


def _build_context(figure, place, era, year: int, extra: dict) -> dict:
    ctx = {
        "figure": figure.name, "role": figure.role, "domain": figure.domain,
        "year": year, "era": era.name,
    }
    if place is not None:
        ctx["place"] = place.name
        ctx["place_noun"] = entities.PLACE_TYPE_NOUN.get(place.place_type, place.place_type.lower())
    ctx.update(extra)
    return ctx


def _maybe_flourish(text: str, template_id: str, rng: random.Random) -> str:
    if template_id not in _NOTABLE_TEMPLATE_IDS:
        return text
    if rng.random() > config.LLM_FLOURISH_RATE or not llm.available():
        return text
    try:
        prompt = (
            "Rewrite the following sentence describing a historical event in "
            "old New York City so it reads as slightly more vivid, period-"
            "flavored prose. Keep every proper noun, name, date, and fact "
            "EXACTLY as given -- do not invent or remove any of them, and "
            "keep it to one sentence. Reply with ONLY the rewritten sentence."
            f"\n\nSentence: {text}"
        )
        flourished = llm.complete(prompt, temperature=0.8).strip().strip('"')
        if flourished and "\n" not in flourished and len(flourished) < len(text) * 3:
            return flourished
    except Exception:
        pass
    return text


# --- effects functions ------------------------------------------------

def _fx_found_place(figure, place, era, year, rng):
    return {}


def _fx_expansion(figure, place, era, year, rng):
    return {}


def _fx_place_destroyed(figure, place, era, year, rng):
    disaster = rng.choice(_DISASTERS)
    place.status = "destroyed"
    place.closed_year = year
    return {"disaster": disaster, "cause": _pick_cause(figure, rng)}


def _fx_rebuilt_place(figure, place, era, year, rng):
    place.status = "active"
    place.closed_year = None
    place.current_owner_figure_id = figure.id
    return {}


def _fx_ownership_change(figure, place, era, year, rng):
    place.current_owner_figure_id = figure.id
    return {"cause": _pick_cause(figure, rng)}


def _fx_renamed(figure, place, era, year, rng):
    old_name = place.name
    surname = figure.name.split()[-1]
    new_name = names.place_name(place.place_type, figure.domain, surname, era.id, rng)
    if new_name == old_name:
        # small fixed word lists can coincidentally regenerate the same
        # name (e.g. two different owners both surnamed "Cohen") -- a
        # rename to an identical name reads as a generator glitch, so force
        # a visible variation instead.
        new_name = f"New {new_name}" if not new_name.startswith("New ") else f"{new_name} & Co."
    place.name = new_name
    return {"old_name": old_name}


def _fx_alliance_formed(figure, place, era, year, rng):
    available = [f for f in entities.FACTIONS if f not in figure.properties["allies"]]
    faction = rng.choice(available or entities.FACTIONS)
    figure.properties["allies"].append(faction)
    return {"faction": faction}


def _fx_rivalry_formed(figure, place, era, year, rng):
    available = [f for f in entities.FACTIONS if f not in figure.properties["rivals"]]
    faction = rng.choice(available or entities.FACTIONS)
    figure.properties["rivals"].append(faction)
    return {"faction": faction}


def _fx_scandal(figure, place, era, year, rng):
    tag = rng.choice(_SCANDAL_TAGS)
    figure.properties["reputation"].append(tag)
    return {"tag": tag, "cause": _pick_cause(figure, rng)}


def _fx_political_trouble(figure, place, era, year, rng):
    outcome = rng.choice(_POLITICAL_OUTCOMES)
    figure.properties["reputation"].append("investigated")
    return {"outcome": outcome, "cause": _pick_cause(figure, rng)}


def _fx_philanthropy(figure, place, era, year, rng):
    figure.properties["reputation"].append("benefactor")
    return {}


def _fx_feud_violence(figure, place, era, year, rng):
    cause = _pick_cause(figure, rng)
    place.properties.setdefault("tags", []).append("site of violence")
    extra = {"cause": cause}
    if figure.alive and rng.random() < 0.12:
        figure.alive = False
        figure.death_year = year
        extra["_text_symbol"] = "TEXT_DEATH"
    return extra


def _fx_visited_by_notable(figure, place, era, year, rng):
    return {}


def _fx_prospered(figure, place, era, year, rng):
    place.properties.setdefault("tags", []).append("renowned")
    return {}


def _fx_decline(figure, place, era, year, rng):
    place.properties.setdefault("tags", []).append("declining")
    return {"cause": _pick_cause(figure, rng)}


def _has_founded_a_place(figure, places):
    return len(figure.properties["founded_places"]) > 0


def _active_place(place, figure):
    return place.status == "active"


def _active_place_not_own(place, figure):
    return place.status == "active" and place.founding_figure_id != figure.id


def _destroyed_place(place, figure):
    return place.status == "destroyed"


_EFFECTS = {
    "found_place": _fx_found_place,
    "expansion": _fx_expansion,
    "place_destroyed": _fx_place_destroyed,
    "rebuilt_place": _fx_rebuilt_place,
    "ownership_change": _fx_ownership_change,
    "renamed": _fx_renamed,
    "alliance_formed": _fx_alliance_formed,
    "rivalry_formed": _fx_rivalry_formed,
    "scandal": _fx_scandal,
    "political_trouble": _fx_political_trouble,
    "philanthropy": _fx_philanthropy,
    "feud_violence": _fx_feud_violence,
    "visited_by_notable": _fx_visited_by_notable,
    "prospered": _fx_prospered,
    "decline": _fx_decline,
}

_PLACE_FILTERS = {
    "active_place": _active_place,
    "active_place_not_own": _active_place_not_own,
    "destroyed_place": _destroyed_place,
}

_PRECONDITIONS = {
    "has_founded_a_place": _has_founded_a_place,
}


def _load_template(raw: dict) -> dict:
    template = {
        "id": raw["id"],
        "requires_place": raw.get("requires_place"),
        "grammar": raw["grammar"],
    }
    if "effects" in raw:
        template["effects"] = _EFFECTS[raw["effects"]]
    if "place_filter" in raw:
        template["place_filter"] = _PLACE_FILTERS[raw["place_filter"]]
    if "precondition" in raw:
        template["precondition"] = _PRECONDITIONS[raw["precondition"]]
    return template


EVENT_TEMPLATES = [_load_template(t) for t in _RAW["event_templates"]]
EVENT_TEMPLATES_BY_ID = {t["id"]: t for t in EVENT_TEMPLATES}

DEATH_TEMPLATE = _RAW["death_template"]


def pick_event_template(figure, places: list, rng: random.Random) -> dict:
    eligible = []
    for template in EVENT_TEMPLATES:
        precondition = template.get("precondition")
        if precondition and not precondition(figure, places):
            continue
        if template["requires_place"] == "existing":
            place_filter = template.get("place_filter")
            if not any((place_filter is None or place_filter(p, figure)) for p in places):
                continue
        eligible.append(template)
    return rng.choice(eligible) if eligible else EVENT_TEMPLATES_BY_ID["found_place"]


def resolve_event(template: dict, figure, places: list, era, year: int, rng: random.Random):
    """Returns (gospel_text, place_or_None, is_new_place)."""
    place = None
    is_new_place = False

    if template["requires_place"] == "new":
        place = _create_place(figure, era, year, rng)
        is_new_place = True
    elif template["requires_place"] == "existing":
        place_filter = template.get("place_filter")
        candidates = [p for p in places if (place_filter is None or place_filter(p, figure))]
        place = rng.choice(candidates)

    extra = dict(template["effects"](figure, place, era, year, rng))
    text_symbol = extra.pop("_text_symbol", "TEXT")
    context = _build_context(figure, place, era, year, extra)
    gospel_text = grammar.expand(template["grammar"], text_symbol, context, rng)
    gospel_text = _maybe_flourish(gospel_text, template["id"], rng)

    return gospel_text, place, is_new_place


def resolve_death(figure, year: int, era, rng: random.Random) -> str:
    figure.alive = False
    figure.death_year = year
    context = _build_context(figure, None, era, year, {})
    return grammar.expand(DEATH_TEMPLATE["grammar"], "TEXT", context, rng)
