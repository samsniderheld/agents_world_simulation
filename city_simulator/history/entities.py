"""Figure and Place entities. Their mutable `properties` bags are exactly
the state the talk this project is modeled on describes: read by
events.py's cause-rationalization (a figure's rivals/allies/domain) and
written by event effects, so later events can reference what earlier ones
established (see events.py's _pick_cause).

The content lists/maps (domains, factions, roles, place types) come from the
current theme's `entities` section (theme.py).
"""

import random
import uuid
from dataclasses import dataclass, field

import theme

from . import names
from .eras import eras_by_id


def new_id(prefix: str) -> str:
    """A per-process sequential counter here would collide across a
    server restart: citystate persists figures/places/characters to disk
    (outliving the process), but a fresh counter always starts back at 1
    -- so the first character added after any restart could silently
    reuse an id already on disk, inheriting that old entity's media/runs/
    plans/treatments (a real bug this caused, not hypothetical). uuid4
    matches citystate/store.py's own media-id scheme for the same reason
    and can't collide with anything already persisted."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _data() -> dict:
    return theme.current()["entities"]


def roles_for_era(era_id: str) -> list:
    return [role for role, eras in _data()["roles"].items() if eras is None or era_id in eras]


def place_types_for_era(era_id: str) -> list:
    return [pt for pt, eras in _data()["place_types"].items() if eras is None or era_id in eras]


def domains_for_era(era_id: str) -> list:
    return _data()["domains"][era_id]


def factions_for_era(era_id: str) -> list:
    return _data()["factions"][era_id]


def place_type_noun(place_type: str, default: str = None) -> str:
    """The plain noun for a place type ("Tavern/Bar" -> "tavern"); `default`
    (or the type itself, lowercased) when the theme doesn't name one."""
    nouns = _data().get("place_type_nouns") or {}
    if place_type in nouns:
        return nouns[place_type]
    return default if default is not None else (place_type or "").lower()


@dataclass
class Figure:
    id: str
    name: str
    role: str
    domain: str
    era_id: str
    birth_year: int
    death_year: int = None
    alive: bool = True
    properties: dict = field(default_factory=lambda: {
        "allies": [], "rivals": [], "reputation": [], "founded_places": [],
    })


@dataclass
class HistoryEntry:
    year: int
    event_id: str
    template_id: str
    figure_id: str
    gospel_text: str


@dataclass
class Place:
    id: str
    name: str
    place_type: str
    domain: str
    founded_year: int
    founding_figure_id: str
    current_owner_figure_id: str
    status: str = "active"          # active | destroyed | closed
    closed_year: int = None
    architecture: str = ""          # one-sentence description; see architecture.py
    properties: dict = field(default_factory=dict)   # free-form tags, e.g. "notorious", "renowned"
    history: list = field(default_factory=list)       # list[HistoryEntry]


def new_figure(era_id: str, rng: random.Random) -> Figure:
    era = eras_by_id()[era_id]
    role = rng.choice(roles_for_era(era_id))
    domain = rng.choice(domains_for_era(era_id))
    birth_year = rng.randint(era.start_year, era.end_year)
    name = names.figure_name(era_id, role, rng)
    return Figure(
        id=new_id("fig_"), name=name, role=role, domain=domain,
        era_id=era_id, birth_year=birth_year,
    )


def new_place(figure: Figure, place_type: str, name: str, year: int, architecture: str = "") -> Place:
    place = Place(
        id=new_id("place_"), name=name, place_type=place_type, domain=figure.domain,
        founded_year=year, founding_figure_id=figure.id, current_owner_figure_id=figure.id,
        architecture=architecture,
    )
    figure.properties["founded_places"].append(place.id)
    return place
