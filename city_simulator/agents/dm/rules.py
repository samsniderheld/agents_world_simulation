"""Dice. d20 + ability modifier against a difficulty class (DC); natural 20
always succeeds (a critical success), natural 1 always fails (a critical
failure). Advantage rolls two d20s and keeps the higher, disadvantage the
lower; they cancel out."""

import dataclasses
import random

STATS = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
STAT_NAMES = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
              "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}
# Trivial tasks are never rolled: they just happen.
DIFFICULTIES = {"trivial": 5, "easy": 10, "medium": 15, "hard": 20, "very hard": 25}

OUTCOME_WORDS = {"crit_success": "critical success", "success": "success",
                 "failure": "failure", "crit_failure": "critical failure"}


def modifier(score: int) -> int:
    return (int(score) - 10) // 2


def difficulty_dc(name: str) -> int:
    return DIFFICULTIES.get((name or "").strip().lower(), DIFFICULTIES["medium"])


def normalise_stat(stat: str) -> str:
    """"Dexterity", "dex", "DEX" -> "DEX" (unknown -> WIS, the catch-all)."""
    s = (stat or "").strip().upper()[:3]
    return s if s in STATS else "WIS"


@dataclasses.dataclass
class CheckResult:
    stat: str
    rolls: list            # the d20s rolled (two with advantage/disadvantage)
    roll: int              # the one that counts
    mod: int
    bonus: int
    total: int
    dc: int
    outcome: str           # crit_success | success | failure | crit_failure
    advantage: int = 0     # +1 advantage, -1 disadvantage, 0 neither

    @property
    def success(self) -> bool:
        return self.outcome in ("success", "crit_success")

    @property
    def critical(self) -> bool:
        return self.outcome.startswith("crit")

    def label(self) -> str:
        """"DEX 7+2=9 vs 15 -- failure" (with "(adv)"/"(disadv)")."""
        sign = "+" if self.mod + self.bonus >= 0 else "-"
        adv = " (adv)" if self.advantage > 0 else " (disadv)" if self.advantage < 0 else ""
        return (f"{self.stat} {self.roll}{sign}{abs(self.mod + self.bonus)}={self.total} vs {self.dc}{adv} "
                f"-- {OUTCOME_WORDS[self.outcome]}")

    def to_dict(self) -> dict:
        return {**dataclasses.asdict(self), "success": self.success}


def roll_d20(rng: random.Random, advantage: int = 0) -> tuple:
    if advantage:
        rolls = [rng.randint(1, 20), rng.randint(1, 20)]
        return rolls, (max(rolls) if advantage > 0 else min(rolls))
    r = rng.randint(1, 20)
    return [r], r


def check(score: int, stat: str, dc: int, rng: random.Random, advantage: int = 0, bonus: int = 0) -> CheckResult:
    advantage = max(-1, min(1, advantage))
    rolls, roll = roll_d20(rng, advantage)
    mod = modifier(score)
    total = roll + mod + bonus
    if roll == 20:
        outcome = "crit_success"
    elif roll == 1:
        outcome = "crit_failure"
    else:
        outcome = "success" if total >= dc else "failure"
    return CheckResult(stat, rolls, roll, mod, bonus, total, dc, outcome, advantage)


def opposed(a_score: int, a_stat: str, b_score: int, b_stat: str, rng: random.Random,
            a_advantage: int = 0, b_advantage: int = 0, a_bonus: int = 0) -> tuple:
    """A contest (persuade vs insight, sneak vs perception): each side
    rolls; the higher total wins, ties go to the defender (b). Crits still
    count for the narration. Returns (a_result, b_result, a_won)."""
    b = check(b_score, b_stat, 0, rng, b_advantage)
    a = check(a_score, a_stat, b.total + 1, rng, a_advantage, a_bonus)
    a_won = a.outcome == "crit_success" or (a.outcome != "crit_failure" and a.total > b.total)
    if a_won and a.outcome == "failure":
        a.outcome = "success"
    if not a_won and a.outcome == "success":
        a.outcome = "failure"
    return a, b, a_won
