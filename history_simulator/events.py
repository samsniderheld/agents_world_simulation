"""Event templates and resolution.

This is the core of the model the talk describes: an event is chosen from
the pool below largely at random (pick_event_template), but *resolving* it
-- deciding a cause, an outcome, who's involved -- reads the figure's
current state (rivals, allies, domain) rather than any real causal
simulation. The cause is a rationalization mediated by that state, exactly
as the talk describes its cats/frogs example: state set by an earlier event
becomes the "reason" a later, otherwise-unrelated event gives for itself.

Each template is a dict:
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

import config
import entities
import grammar
import llm
import names

_GENERIC_CAUSES = [
    # domain values may themselves start with "the" (e.g. "the press"), so
    # these deliberately don't prepend their own article before {domain}.
    "a matter of {domain}",
    "reasons the old records leave unclear",
    "a dispute no one now remembers clearly",
    "what was once called simply \"{domain} business\"",
]


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


# A subset of dramatic event kinds get a shot at an LLM prose flourish
# (config.LLM_FLOURISH_RATE); everything else stays pure grammar output.
_NOTABLE_TEMPLATE_IDS = {"found_place", "place_destroyed", "rebuilt_place", "expansion"}


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
    # Mixed articles are deliberate: every template phrases these as
    # "lost to {disaster}" / "consumed by {disaster}", which both read fine
    # whether or not the phrase itself carries an article.
    disaster = rng.choice(["fire", "a storm", "a riot", "a flood"])
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
    tag = rng.choice(["bribery", "smuggling", "adultery", "embezzlement", "blasphemy", "forgery"])
    figure.properties["reputation"].append(tag)
    return {"tag": tag, "cause": _pick_cause(figure, rng)}


def _fx_political_trouble(figure, place, era, year, rng):
    outcome = rng.choice([
        "a night in the Tombs", "a heavy fine", "a public apology",
        "quiet exile from the ward", "a pardon bought with favors",
    ])
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


EVENT_TEMPLATES = [
    {
        "id": "found_place", "requires_place": "new", "effects": _fx_found_place,
        "grammar": {
            "TEXT": [
                "In {year}, {figure} of {domain} founded {place}, a {place_noun}, {founding_flourish}.",
                "{figure} opened the doors of {place} in {year}, a {place_noun} that would carry the mark of {domain} for years to come.",
            ],
            "founding_flourish": [
                "on a corner that was then little more than mud and ambition",
                "with borrowed money and a great deal of nerve",
                "in the shadow of the harbor",
                "on ground still remembered as farmland",
            ],
        },
    },
    {
        "id": "expansion", "requires_place": "new", "effects": _fx_expansion,
        "precondition": _has_founded_a_place,
        "grammar": {
            "TEXT": [
                "Flush with earlier success, {figure} opened a second {place_noun}, {place}, in {year}.",
                "By {year}, {figure}'s ambitions had outgrown one address; {place}, a new {place_noun}, followed.",
            ],
        },
    },
    {
        "id": "place_destroyed", "requires_place": "existing", "place_filter": _active_place,
        "effects": _fx_place_destroyed,
        "grammar": {
            "TEXT": [
                "In {year}, {place} was lost to {disaster}; some blamed {cause}.",
                "{place} was consumed by {disaster} in {year}, leaving little of what {figure} had built there.",
            ],
        },
    },
    {
        "id": "rebuilt_place", "requires_place": "existing", "place_filter": _destroyed_place,
        "effects": _fx_rebuilt_place,
        "grammar": {
            "TEXT": [
                "{figure} rebuilt {place} in {year}, raising it again as a {place_noun}.",
                "Where ashes had stood, {figure} raised {place} anew in {year}.",
            ],
        },
    },
    {
        "id": "ownership_change", "requires_place": "existing", "place_filter": _active_place,
        "effects": _fx_ownership_change,
        "grammar": {
            "TEXT": [
                "{place}, the old {place_noun}, changed hands in {year} when {figure} took it over.",
                "In {year}, {figure} bought out the previous proprietor of {place}, citing {cause}.",
            ],
        },
    },
    {
        "id": "renamed", "requires_place": "existing", "place_filter": _active_place,
        "effects": _fx_renamed,
        "grammar": {
            "TEXT": [
                "{figure} renamed the old {place_noun} -- once known as {old_name} -- to {place} in {year}.",
            ],
        },
    },
    {
        "id": "alliance_formed", "requires_place": None, "effects": _fx_alliance_formed,
        "grammar": {
            "TEXT": [
                "By {year}, {figure} had made fast friends with {faction}, a bond that would shape years to come.",
                "{figure} threw in with {faction} in {year}, for {domain}'s sake if nothing else.",
            ],
        },
    },
    {
        "id": "rivalry_formed", "requires_place": None, "effects": _fx_rivalry_formed,
        "grammar": {
            "TEXT": [
                "In {year}, {figure} earned the lasting enmity of {faction}.",
                "{figure} and {faction} became bitter rivals in {year}, over {domain} as much as anything else.",
            ],
        },
    },
    {
        "id": "scandal", "requires_place": None, "effects": _fx_scandal,
        "grammar": {
            "TEXT": [
                "Rumors of {tag} dogged {figure} from {year} onward, whispered to be over {cause}.",
            ],
        },
    },
    {
        "id": "political_trouble", "requires_place": None, "effects": _fx_political_trouble,
        "grammar": {
            "TEXT": [
                "{figure} was hauled before the magistrates in {year} over {cause}, and it ended in {outcome}.",
            ],
        },
    },
    {
        "id": "philanthropy", "requires_place": "existing", "place_filter": _active_place,
        "effects": _fx_philanthropy,
        "grammar": {
            "TEXT": [
                "{figure} funded repairs to {place} in {year}, out of devotion to {domain} -- or so it was said.",
            ],
        },
    },
    {
        "id": "feud_violence", "requires_place": "existing", "place_filter": _active_place,
        "effects": _fx_feud_violence,
        "grammar": {
            "TEXT": [
                "Blood was spilled at {place} in {year} over {cause}.",
                "A brawl broke out at {place} in {year}, said to be about {cause}.",
            ],
            "TEXT_DEATH": [
                "{figure} was killed in a brawl at {place} in {year} over {cause} -- the {place_noun} was never quite the same.",
            ],
        },
    },
    {
        "id": "visited_by_notable", "requires_place": "existing", "place_filter": _active_place_not_own,
        "effects": _fx_visited_by_notable,
        "grammar": {
            "TEXT": [
                "{figure} was known to frequent {place} around {year}, and the old {place_noun} was never quite the same after.",
            ],
        },
    },
    {
        "id": "prospered", "requires_place": "existing", "place_filter": _active_place,
        "effects": _fx_prospered,
        "grammar": {
            "TEXT": [
                "{place} prospered under {figure}'s hand, and by {year} its name was known across the city.",
            ],
        },
    },
    {
        "id": "decline", "requires_place": "existing", "place_filter": _active_place,
        "effects": _fx_decline,
        "grammar": {
            "TEXT": [
                "By {year}, {place} had fallen on hard times, a decline some blamed on {cause}.",
            ],
        },
    },
]

EVENT_TEMPLATES_BY_ID = {t["id"]: t for t in EVENT_TEMPLATES}

DEATH_TEMPLATE = {
    "id": "death",
    "grammar": {
        "TEXT": [
            "{figure} died in {year}, remembered -- if at all -- for their ties to {domain}.",
            "By {year}, {figure} was gone, and whatever they had built was left to others to keep or lose.",
        ],
    },
}


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
