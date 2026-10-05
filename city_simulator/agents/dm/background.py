"""Dice for CITY background residents -- no LLM at all. When a resident
starts a schedule block, the activity is matched to a kind (work, drink,
errands, ...) from the theme's `city_life.dice` table, which says what it
tests and how hard it may be; code rolls, a theme template says what
happened, and the sheet takes the mood, money and condition effects.
"""

import random
import re

import theme

from . import effects, rules
from .stats import _archetype


def table() -> dict:
    """The current theme's `city_life.dice`, or the default theme's."""
    dice = (theme.current()["city_life"] or {}).get("dice")
    return dice or theme.default()["city_life"]["dice"]


def classify(activity: str) -> tuple:
    """(kind, spec) for an activity: the first kind with a keyword in it,
    else the last kind (the catch-all)."""
    kinds = table()["activities"]
    text = (activity or "").lower()
    for kind, spec in kinds.items():
        if any(re.search(rf"\b{re.escape(k.lower())}\b", text) for k in spec.get("keywords") or []):
            return kind, spec
    kind = list(kinds)[-1]
    return kind, kinds[kind]


def roll_block(agent, sheet, activity: str, where: str, rng: random.Random):
    """Roll for one schedule block (`where`: "at Ozzy's Bar", "at home",
    "somewhere across town"). None for a routine (trivial) one;
    otherwise {"kind", "result", "text", "notes", "money"} -- the sheet
    already updated."""
    dice = table()
    kind, spec = classify(activity)
    difficulty = rng.choice(spec.get("difficulty") or ["trivial"])
    if difficulty not in rules.DIFFICULTIES or difficulty == "trivial":
        return None
    stat = spec.get("stat") or "WIS"
    stat = _archetype(f"{agent.occupation} {agent.bio}")[0][0] if stat == "job" else rules.normalise_stat(stat)
    result = rules.check(sheet.score(stat), stat, rules.difficulty_dc(difficulty), rng, advantage=sheet.advantage(stat))
    notes = effects.apply_check(sheet, result)

    money = 0
    low, high = (dice.get("money") or {}).get(kind, (0, 0))
    if low >= 0:            # earning: only on a success, double on a crit
        if result.success:
            money = rng.randint(low, high) * (2 if result.outcome == "crit_success" else 1)
    elif result.outcome != "crit_success":   # spending: a crit means someone else paid
        money = rng.randint(low, high) * (3 if result.outcome == "crit_failure" else 1)
    money = max(money, -sheet.money)
    if money:
        sheet.money += money
        notes.append(f"{money:+d} money")

    lines = ((dice.get("outcomes") or {}).get(kind) or {}).get(result.outcome) or ["{name}: {activity} -- {outcome}."]
    text = theme.fill(rng.choice(lines), {"name": agent.name, "activity": activity, "where": where,
                                          "outcome": rules.OUTCOME_WORDS[result.outcome]})
    return {"kind": kind, "result": result, "text": text, "notes": notes, "money": money}
