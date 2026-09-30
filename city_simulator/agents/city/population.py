"""Background residents for CITY mode: up to thousands of people built from
the city's own data -- names.yaml's period name pools, the active places
and their types, era roles -- with history/grammar.py writing each one-line
bio. No LLM calls at all, and deterministic from a seed: resident i is
always built from Random(f"{seed}:{i}"), so asking for 200 and later for
1000 gives the same first 200.

Each resident gets a workplace (an active place whose type employs people,
or off the map), a haunt (somewhere they spend free time), a home (a
residential place on the map, or a private home off it), an occupation that
fits the workplace, and a day or night shift. template_schedule() turns
that into a day's plan when the LLM isn't asked (or fails).
"""

import random

from history import grammar
from history import names as history_names

from .tiers import ELSEWHERE, HOME, Block

# Occupations by the type of place someone works at.
WORK_ROLES = {
    "Tavern/Bar": ["bartender", "barback", "cocktail waitress", "short-order cook"],
    "Inn": ["innkeeper", "chambermaid"],
    "Coffee House": ["counterman", "waitress"],
    "Speakeasy": ["doorman", "bartender"],
    "Cocktail Lounge": ["lounge pianist", "cocktail waitress", "bartender", "hat-check girl"],
    "Nightclub/Jazz Club": ["jazz trumpeter", "cigarette girl", "bouncer", "club singer", "drummer"],
    "Brewery": ["brewer", "delivery driver", "bottler"],
    "Restaurant": ["waiter", "line cook", "dishwasher", "maître d'"],
    "Diner/Automat": ["short-order cook", "waitress", "counterman", "busboy"],
    "Hotel/Boarding House": ["desk clerk", "bellhop", "chambermaid", "night porter"],
    "Grocery/Corner Store": ["grocer's clerk", "stock boy", "delivery boy"],
    "Supermarket": ["checkout girl", "butcher", "stock clerk"],
    "Market": ["fishmonger", "produce vendor", "butcher"],
    "Department Store": ["shopgirl", "floorwalker", "window dresser", "elevator operator"],
    "Pawnshop": ["pawnbroker's clerk"],
    "Garage/Filling Station": ["mechanic", "pump jockey", "tow-truck driver"],
    "Factory/Mill": ["machinist", "foreman", "loom operator", "shift worker"],
    "Shipyard/Dock/Warehouse": ["longshoreman", "crane operator", "night watchman", "dock clerk", "teamster"],
    "Bank/Counting House": ["bank teller", "loan officer", "security guard"],
    "Union Hall": ["union steward", "hall secretary"],
    "Newspaper/Print Shop": ["copy boy", "typesetter", "beat reporter", "press operator"],
    "Radio Station": ["radio announcer", "sound engineer", "switchboard operator"],
    "Theater/Hall": ["usher", "stagehand", "box-office clerk", "chorus girl"],
    "Dance Hall": ["taxi dancer", "bandleader"],
    "Movie Palace": ["projectionist", "usher", "candy-counter girl"],
    "Pool Hall": ["pool hustler", "rack boy"],
    "Policy Shop/Gambling Den": ["numbers runner", "bookie's clerk", "lookout"],
    "Church/House of Worship": ["sexton", "choir director", "parish secretary"],
    "School": ["schoolteacher", "janitor", "school nurse"],
    "Hospital": ["nurse", "orderly", "ambulance driver", "night-shift intern"],
    "Government/Civic Building": ["city clerk", "beat cop", "court stenographer", "building inspector"],
    "Social/Fraternal Club": ["club steward", "card dealer"],
    "Park/Public Square": ["parks attendant", "hot-dog vendor", "shoeshine boy"],
    "Apartment House": ["building superintendent", "doorman"],
    "Housing Project": ["housing caretaker"],
}
OFF_MAP_ROLES = ["cab driver", "subway motorman", "garment worker", "insurance salesman", "housewife",
                 "retired longshoreman", "seamstress", "out-of-work boxer", "milkman", "typist",
                 "door-to-door salesman", "widow living on a pension", "night-school student",
                 "private-duty nurse", "pensioner"]
NIGHT_ROLES = {"bartender", "barback", "cocktail waitress", "lounge pianist", "jazz trumpeter", "cigarette girl",
               "bouncer", "club singer", "drummer", "night porter", "night watchman", "doorman",
               "night-shift intern", "taxi dancer", "bandleader", "projectionist", "numbers runner", "lookout",
               "hat-check girl", "card dealer"}
RESIDENTIAL = {"Tenement/Residence", "Brownstone/Townhouse", "Apartment House", "Housing Project",
               "Hotel/Boarding House"}
LEISURE = {"Tavern/Bar", "Coffee House", "Cocktail Lounge", "Nightclub/Jazz Club", "Restaurant",
           "Diner/Automat", "Pool Hall", "Movie Palace", "Theater/Hall", "Dance Hall", "Park/Public Square",
           "Church/House of Worship", "Social/Fraternal Club", "Market", "Department Store",
           "Policy Shop/Gambling Den", "Speakeasy"}

BIO_GRAMMAR = {
    "bio": [
        "{name} is a {occupation} {where}, {trait}.",
        "{name} works as a {occupation} {where} and {habit}.",
        "A {occupation} {where}, {name} {habit}.",
        "{name}, {occupation} {where}, is {trait}.",
    ],
    "trait": ["known for never missing a day", "quiet and hard to read", "quick with a joke and slow to trust",
              "saving every spare dime for something nobody else knows about", "a little too curious about other people's business",
              "tired in a way sleep doesn't fix", "proud of a neighborhood that has seen better days",
              "careful to stay on the right side of the cops", "owed money by half the block",
              "still sending money home to family overseas", "the first to hear any rumor on the street"],
    "habit": ["reads the racing form on every break", "keeps a flask in a coat pocket", "hums old songs under their breath",
              "never sits with their back to the door", "feeds the pigeons on the way home",
              "plays the numbers every single day", "writes letters nobody answers",
              "knows every beat cop by first name", "counts their change twice", "walks the long way home to avoid someone"],
}


def _given_and_surnames() -> tuple:
    """Everyone alive in 1959 has a 20th-century or 19th-century immigrant
    name (names.yaml's "20c" and "19c" groups)."""
    groups = history_names._NAME_GROUPS
    given = list(dict.fromkeys(groups["20c"]["given"] + groups["19c"]["given"]))
    surnames = list(dict.fromkeys(groups["20c"]["surname"] + groups["19c"]["surname"]))
    return given, surnames


def generate(city: dict, count: int, seed: int, taken_names: set = (), start: int = 0,
             existing: list = ()) -> list:
    """Residents start..count-1 (appending to `existing`, which holds
    residents 0..start-1 from an earlier call). `taken_names` (the heroes)
    are never reused."""
    places = [p for p in (city or {}).get("places", []) if p.get("status") == "active" and p.get("name")]
    workplaces = [p for p in places if p.get("place_type") in WORK_ROLES]
    homes = [p["name"] for p in places if p.get("place_type") in RESIDENTIAL]
    leisure = [p["name"] for p in places if p.get("place_type") in LEISURE] or [p["name"] for p in places]
    given, surnames = _given_and_surnames()
    used = set(taken_names) | {r["name"] for r in existing}
    out = list(existing)
    for i in range(start, count):
        rng = random.Random(f"{seed}:{i}")
        name = f"{rng.choice(given)} {rng.choice(surnames)}"
        if name in used:
            first, last = name.split(" ", 1)
            name = f"{first} {rng.choice('ABCDEFGHJKLMNPRSTW')}. {last}"
            k = 2
            while name in used:
                name = f"{first} {rng.choice('ABCDEFGHJKLMNPRSTW')}. {last}" if k < 6 else f"{first} {last} {k}"
                k += 1
        used.add(name)
        # Most people with a mapped workplace work there; the rest work
        # somewhere off the map (and so only meet others in their free time).
        if workplaces and rng.random() < 0.7:
            work_place = rng.choice(workplaces)
            occupation = rng.choice(WORK_ROLES[work_place["place_type"]])
            work = work_place["name"]
            where = f"at {work}"
        else:
            occupation, work = rng.choice(OFF_MAP_ROLES), None
            where = "across town"
        age = rng.randint(19, 78)
        if age >= 66 and rng.random() < 0.6:
            occupation, work, where = "retiree", None, "in the neighborhood"
        haunt = rng.choice(leisure) if leisure else None
        record = {
            "id": f"bg_{i:05d}",
            "name": name,
            "age": age,
            "occupation": occupation,
            "work": work,
            "haunt": haunt,
            "home": rng.choice(homes) if homes and rng.random() < 0.5 else None,
            "shift": "night" if occupation in NIGHT_ROLES else "day",
            "bio": grammar.expand(BIO_GRAMMAR, "bio", {"name": name, "occupation": occupation, "where": where}, rng),
        }
        out.append(record)
    return out


def template_schedule(agent, rng: random.Random) -> list:
    """A plausible day for someone of this occupation and shift, with the
    times jittered per person so the whole city doesn't move at once."""
    j = rng.randint(-20, 20)

    def t(h, m=0):
        return max(0, min(1440, h * 60 + m + j))

    work = agent.work or ELSEWHERE
    haunt = agent.haunt or HOME
    job = f"working as a {agent.occupation}"
    if agent.occupation in ("retiree", "pensioner", "widow living on a pension"):
        return [Block(0, t(7), "asleep", HOME), Block(t(7), t(10), "breakfast and the morning paper", HOME),
                Block(t(10), t(13), "passing the time", haunt), Block(t(13), t(17), "running errands", ELSEWHERE),
                Block(t(17), t(20), "an early supper and conversation", haunt), Block(t(20), 1440, "the radio, then bed", HOME)]
    if agent.shift == "night":
        return [Block(0, t(2, 30), job, work), Block(t(2, 30), t(11), "asleep", HOME),
                Block(t(11), t(13), "coffee and a late breakfast", HOME), Block(t(13), t(16), "errands around town", ELSEWHERE),
                Block(t(16), t(18), "killing time before the shift", haunt), Block(t(18), 1440, job, work)]
    return [Block(0, t(6, 30), "asleep", HOME), Block(t(6, 30), t(8), "getting ready for work", HOME),
            Block(t(8), t(12), job, work), Block(t(12), t(13), "lunch", haunt),
            Block(t(13), t(17, 30), job, work), Block(t(17, 30), t(20), "unwinding after work", haunt),
            Block(t(20), 1440, "at home for the night", HOME)]


def schedule_places(city: dict) -> list:
    """What a background schedule may name: every active place, plus home
    and elsewhere."""
    places = sorted({p["name"] for p in (city or {}).get("places", []) if p.get("status") == "active" and p.get("name")})
    return places + [HOME, ELSEWHERE]
