"""Rolling a stat block for someone from their occupation and bio -- no LLM,
deterministic from a seed key (their id). Six rolls of 4d6-drop-lowest,
sorted, handed out in the order their archetype cares about."""

import random

from .rules import STATS
from .sheet import CharacterSheet

# (keywords in occupation/bio, stat priority, starting money range)
ARCHETYPES = [
    (("boss", "mob", "gang", "fixer", "racketeer", "thief-lord", "bookie", "numbers", "syndicate", "lord"),
     ["CHA", "WIS", "INT", "DEX", "CON", "STR"], (150, 900)),
    (("detective", "eye", "investigator", "reporter", "watch", "sergeant", "captain", "cop", "inspector"),
     ["WIS", "INT", "DEX", "CON", "CHA", "STR"], (20, 150)),
    (("singer", "musician", "bard", "player", "dancer", "performer", "pianist", "trumpeter", "girl", "host"),
     ["CHA", "DEX", "WIS", "CON", "INT", "STR"], (10, 120)),
    (("longshoreman", "dock", "teamster", "smith", "farrier", "bouncer", "boxer", "porter", "guard", "laborer",
      "mason", "stevedore", "crane", "caulker", "hauler"), ["STR", "CON", "DEX", "WIS", "CHA", "INT"], (5, 60)),
    (("doctor", "physician", "nurse", "healer", "scholar", "scribe", "librarian", "wizard", "alchemist", "editor",
      "clerk", "teller", "typist", "engineer", "copyist", "apothecary"), ["INT", "WIS", "DEX", "CON", "CHA", "STR"], (20, 200)),
    (("priest", "reverend", "acolyte", "sexton", "shrine", "monk", "nun"), ["WIS", "CHA", "INT", "CON", "STR", "DEX"], (5, 60)),
    (("merchant", "owner", "keeper", "innkeeper", "grocer", "pawnbroker", "moneychanger", "banker", "loan", "vintner"),
     ["CHA", "INT", "WIS", "CON", "DEX", "STR"], (80, 500)),
    (("bartender", "tapster", "waiter", "waitress", "cook", "serving", "busboy", "counterman", "chambermaid", "bellhop"),
     ["CHA", "DEX", "CON", "WIS", "STR", "INT"], (10, 80)),
    (("runner", "lookout", "pickpocket", "hustler", "smuggler", "sneak", "cab", "driver", "messenger"),
     ["DEX", "WIS", "CHA", "CON", "INT", "STR"], (5, 90)),
]
DEFAULT = (["CON", "WIS", "DEX", "CHA", "STR", "INT"], (5, 80))


def _archetype(text: str):
    text = (text or "").lower()
    for keywords, order, money in ARCHETYPES:
        if any(k in text for k in keywords):
            return order, money
    return DEFAULT


def roll_for(occupation: str, bio: str, seed_key: str) -> CharacterSheet:
    rng = random.Random(f"stats:{seed_key}")
    order, (low, high) = _archetype(f"{occupation} {bio}")
    rolls = sorted((sum(sorted(rng.randint(1, 6) for _ in range(4))[1:]) for _ in range(6)), reverse=True)
    stats = {stat: score for stat, score in zip(order, rolls)}
    return CharacterSheet(stats={s: stats[s] for s in STATS}, money=rng.randint(low, high))


def sheet_from_record(record: dict, seed_key: str = None) -> CharacterSheet:
    """A character's or resident's saved sheet, or a fresh roll for one
    who's never had one."""
    if record.get("sheet"):
        return CharacterSheet.from_dict(record["sheet"])
    return roll_for(record.get("occupation") or "", record.get("bio") or "", seed_key or record.get("id") or record.get("name", ""))
