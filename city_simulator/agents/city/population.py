"""Background residents for CITY mode: up to thousands of people built from
the city's own data -- the theme's period name pools, the active places
and their types, its city_life jobs and bio grammar (theme.py) -- with
history/grammar.py writing each one-line bio. No LLM calls at all, and deterministic from a seed: resident i is
always built from Random(f"{seed}:{i}"), so asking for 200 and later for
1000 gives the same first 200.

Each resident gets a workplace (an active place whose type employs people,
or off the map), a haunt (somewhere they spend free time), a home (a
residential place on the map, or a private home off it), an occupation that
fits the workplace, and a day or night shift. template_schedule() turns
that into a day's plan when the LLM isn't asked (or fails).
"""

import random

import theme
from history import grammar
from history import names as history_names  # noqa: F401 -- kept for callers that patch it

from .tiers import ELSEWHERE, HOME, Block


def _life() -> dict:
    """The current theme's `city_life` section: work_roles (place type ->
    occupations), off_map_roles, night_roles, retired_roles,
    residential/leisure place types, bio_grammar, schedule_activities, ..."""
    return theme.current()["city_life"]


def _given_and_surnames() -> tuple:
    """Residents' names: the theme's resident_name_groups (for the noir
    theme, the "20c" and "19c" name groups -- everyone alive in 1959),
    merged in order without repeats."""
    groups = theme.current()["names"]["name_groups"]
    chosen = _life()["resident_name_groups"]
    given = list(dict.fromkeys(g for group in chosen for g in groups[group]["given"]))
    surnames = list(dict.fromkeys(s for group in chosen for s in groups[group]["surname"]))
    return given, surnames


def generate(city: dict, count: int, seed: int, taken_names: set = (), start: int = 0,
             existing: list = ()) -> list:
    """Residents start..count-1 (appending to `existing`, which holds
    residents 0..start-1 from an earlier call). `taken_names` (the heroes)
    are never reused."""
    life = _life()
    work_roles = life["work_roles"]
    residential, leisure_types = set(life["residential_place_types"]), set(life["leisure_place_types"])
    night_roles = set(life["night_roles"])
    places = [p for p in (city or {}).get("places", []) if p.get("status") == "active" and p.get("name")]
    workplaces = [p for p in places if p.get("place_type") in work_roles]
    homes = [p["name"] for p in places if p.get("place_type") in residential]
    leisure = [p["name"] for p in places if p.get("place_type") in leisure_types] or [p["name"] for p in places]
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
            occupation = rng.choice(work_roles[work_place["place_type"]])
            work = work_place["name"]
            where = theme.fill(life["where_at_work"], {"work": work})
        else:
            occupation, work = rng.choice(life["off_map_roles"]), None
            where = life["where_off_map"]
        age = rng.randint(19, 78)
        if age >= 66 and rng.random() < 0.6:
            occupation, work, where = life["retiree"], None, life["where_retired"]
        haunt = rng.choice(leisure) if leisure else None
        record = {
            "id": f"bg_{i:05d}",
            "name": name,
            "age": age,
            "occupation": occupation,
            "work": work,
            "haunt": haunt,
            "home": rng.choice(homes) if homes and rng.random() < 0.5 else None,
            "shift": "night" if occupation in night_roles else "day",
            "bio": grammar.expand(life["bio_grammar"], "bio", {"name": name, "occupation": occupation, "where": where}, rng),
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
    life = _life()
    a = life["schedule_activities"]
    job = theme.fill(a["working"], {"occupation": agent.occupation})
    if agent.occupation in life["retired_roles"]:
        return [Block(0, t(7), a["asleep"], HOME), Block(t(7), t(10), a["retired_breakfast"], HOME),
                Block(t(10), t(13), a["retired_haunt"], haunt), Block(t(13), t(17), a["retired_errands"], ELSEWHERE),
                Block(t(17), t(20), a["retired_supper"], haunt), Block(t(20), 1440, a["retired_night"], HOME)]
    if agent.shift == "night":
        return [Block(0, t(2, 30), job, work), Block(t(2, 30), t(11), a["asleep"], HOME),
                Block(t(11), t(13), a["night_breakfast"], HOME), Block(t(13), t(16), a["night_errands"], ELSEWHERE),
                Block(t(16), t(18), a["night_haunt"], haunt), Block(t(18), 1440, job, work)]
    return [Block(0, t(6, 30), a["asleep"], HOME), Block(t(6, 30), t(8), a["day_getting_ready"], HOME),
            Block(t(8), t(12), job, work), Block(t(12), t(13), a["day_lunch"], haunt),
            Block(t(13), t(17, 30), job, work), Block(t(17, 30), t(20), a["day_unwinding"], haunt),
            Block(t(20), 1440, a["day_home"], HOME)]


def schedule_places(city: dict) -> list:
    """What a background schedule may name: every active place, plus home
    and elsewhere."""
    places = sorted({p["name"] for p in (city or {}).get("places", []) if p.get("status") == "active" and p.get("name")})
    return places + [HOME, ELSEWHERE]
