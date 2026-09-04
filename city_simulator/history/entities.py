"""Figure and Place entities. Their mutable `properties` bags are exactly
the state the talk this project is modeled on describes: read by
events.py's cause-rationalization (a figure's rivals/allies/domain) and
written by event effects, so later events can reference what earlier ones
established (see events.py's _pick_cause).

The content lists/maps below (domains, factions, roles, place types) live
in entities.yaml; this module just loads them.
"""

import itertools
import random
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import names
from .eras import ERAS_BY_ID

_YAML_PATH = Path(__file__).parent / "data" / "entities.yaml"

with open(_YAML_PATH) as _f:
    _RAW = yaml.safe_load(_f)

_id_counter = itertools.count(1)


def new_id(prefix: str) -> str:
    return f"{prefix}{next(_id_counter)}"


DOMAINS = _RAW["domains"]
FACTIONS = _RAW["factions"]
ROLES = _RAW["roles"]
PLACE_TYPES = _RAW["place_types"]
PLACE_TYPE_NOUN = _RAW["place_type_nouns"]


def roles_for_era(era_id: str) -> list:
    return [role for role, eras in ROLES.items() if eras is None or era_id in eras]


def place_types_for_era(era_id: str) -> list:
    return [pt for pt, eras in PLACE_TYPES.items() if eras is None or era_id in eras]


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
    properties: dict = field(default_factory=dict)   # free-form tags, e.g. "notorious", "renowned"
    history: list = field(default_factory=list)       # list[HistoryEntry]


def new_figure(era_id: str, rng: random.Random) -> Figure:
    era = ERAS_BY_ID[era_id]
    role = rng.choice(roles_for_era(era_id))
    domain = rng.choice(DOMAINS)
    birth_year = rng.randint(era.start_year, era.end_year)
    name = names.figure_name(era_id, role, rng)
    return Figure(
        id=new_id("fig_"), name=name, role=role, domain=domain,
        era_id=era_id, birth_year=birth_year,
    )


def new_place(figure: Figure, place_type: str, name: str, year: int) -> Place:
    place = Place(
        id=new_id("place_"), name=name, place_type=place_type, domain=figure.domain,
        founded_year=year, founding_figure_id=figure.id, current_owner_figure_id=figure.id,
    )
    figure.properties["founded_places"].append(place.id)
    return place
