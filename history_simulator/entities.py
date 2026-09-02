"""Figure and Place entities. Their mutable `properties` bags are exactly
the state the talk this project is modeled on describes: read by
events.py's cause-rationalization (a figure's rivals/allies/domain) and
written by event effects, so later events can reference what earlier ones
established (see events.py's _pick_cause).
"""

import itertools
import random
from dataclasses import dataclass, field

import names
from eras import ERAS_BY_ID

_id_counter = itertools.count(1)


def new_id(prefix: str) -> str:
    return f"{prefix}{next(_id_counter)}"


# Recurring thematic motifs assigned to a Figure at creation (Qud's
# fire/ice "domain") -- inherited by any Place they found, coloring that
# place's language for its whole history even after ownership changes.
DOMAINS = [
    "the harbor", "iron", "smoke", "the ledger", "temperance", "brass",
    "the tide", "granite", "the press", "steam", "the vote", "velvet",
    "frost", "the pulpit", "salt", "copper",
]

# Abstract allegiance targets a figure can become allied/rival with --
# the direct analog of the talk's "frogs"/"cats" factions.
FACTIONS = [
    "the dockworkers", "the harbor pilots", "the temperance league", "the ward bosses",
    "the immigrant aid society", "the press", "the constabulary", "the abolitionists",
    "the merchants' guild", "the parish poor", "the longshoremen", "the suffragists",
    "the volunteer firemen", "the stagehands' union", "the settlement house",
]

# role -> list of valid era ids, or None for "any era"
ROLES = {
    "Merchant": None,
    "Ship Captain": ["dutch_colonial", "english_colonial", "early_republic", "antebellum", "gilded_age"],
    "Alderman": ["english_colonial", "early_republic", "antebellum", "gilded_age", "progressive"],
    "Reverend": None,
    "Tavern Keeper": None,
    "Madam": ["antebellum", "gilded_age", "progressive", "prohibition"],
    "Gang Boss": ["antebellum", "gilded_age", "progressive", "prohibition"],
    "Industrialist": ["gilded_age", "progressive", "depression_war"],
    "Newspaper Editor": ["early_republic", "antebellum", "gilded_age", "progressive", "prohibition", "depression_war"],
    "Union Organizer": ["progressive", "prohibition", "depression_war"],
    "Speakeasy Owner": ["prohibition"],
    "Physician": None,
    "Architect": ["early_republic", "antebellum", "gilded_age", "progressive", "depression_war"],
    "Immigrant Entrepreneur": ["antebellum", "gilded_age", "progressive", "prohibition", "depression_war"],
    "Society Matron": ["gilded_age", "progressive", "depression_war"],
    "Police Captain": ["antebellum", "gilded_age", "progressive", "prohibition", "depression_war"],
}

# place_type -> list of valid era ids, or None for "any era"
PLACE_TYPES = {
    "Tavern/Bar": None,
    "Restaurant": None,
    "General Store/Shop": None,
    "Market": None,
    "Church/House of Worship": None,
    "Theater/Hall": ["early_republic", "antebellum", "gilded_age", "progressive", "prohibition", "depression_war"],
    "Hotel/Boarding House": None,
    "Newspaper/Print Shop": ["early_republic", "antebellum", "gilded_age", "progressive", "prohibition", "depression_war"],
    "Shipyard/Dock/Warehouse": None,
    "Bank/Counting House": None,
    "Tenement/Residence": ["antebellum", "gilded_age", "progressive", "prohibition", "depression_war"],
    "Park/Public Square": None,
    "Government/Civic Building": None,
    "Factory/Mill": ["gilded_age", "progressive", "prohibition", "depression_war"],
    "Speakeasy": ["prohibition"],
    "Department Store": ["gilded_age", "progressive", "prohibition", "depression_war"],
    "Social/Fraternal Club": None,
    "School": None,
}

PLACE_TYPE_NOUN = {
    "Tavern/Bar": "tavern", "Restaurant": "restaurant", "General Store/Shop": "general store",
    "Market": "market", "Church/House of Worship": "church", "Theater/Hall": "theater",
    "Hotel/Boarding House": "hotel", "Newspaper/Print Shop": "print shop",
    "Shipyard/Dock/Warehouse": "shipyard", "Bank/Counting House": "counting house",
    "Tenement/Residence": "tenement", "Park/Public Square": "public square",
    "Government/Civic Building": "civic hall", "Factory/Mill": "mill",
    "Speakeasy": "speakeasy", "Department Store": "department store",
    "Social/Fraternal Club": "social club", "School": "schoolhouse",
}


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
