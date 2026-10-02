"""CharacterSheet: what the DM tracks about an agent between checks.

    stats          {"STR": 8..18, ...}
    mood           -3..+3 (devastated .. elated) plus the word for how the last
                   big moment left them ("rattled", "triumphant"); drifts one
                   step back toward steady each tick
    relationships  {name: attitude -100..100} -> hostile .. loyal
    goals          [{text, progress 0..3, status active|achieved|failed}]
    conditions     {name: ticks left} -- see CONDITIONS
    money          an amount in the theme's currency

Persisted as a dict (to_dict/from_dict): a character's lives in their
agent.json ("sheet"), a background resident's in background.json.
"""

import dataclasses

from .rules import STATS, modifier

MOOD_LABELS = {-3: "devastated", -2: "upset", -1: "uneasy", 0: "steady", 1: "content", 2: "pleased", 3: "elated"}

# name -> (advantage per stat, default duration in ticks, how it reads in a prompt)
CONDITIONS = {
    "injured": ({"STR": -1, "DEX": -1}, 6, "injured"),
    "exhausted": ({"STR": -1, "DEX": -1, "CON": -1}, 4, "exhausted"),
    "drunk": ({"DEX": -1, "INT": -1, "WIS": -1, "CHA": 1}, 3, "drunk"),
    "shaken": ({"WIS": -1, "CHA": -1}, 3, "shaken"),
    "humiliated": ({"CHA": -1}, 4, "humiliated"),
    "inspired": ({s: 1 for s in STATS}, 2, "inspired"),
    "wanted": ({}, 12, "wanted by someone"),
}

ATTITUDES = [(-60, "hostile"), (-25, "unfriendly"), (-5, "wary"), (5, "neutral"), (40, "friendly"), (101, "loyal")]


def attitude_label(value: int) -> str:
    for upper, label in ATTITUDES:
        if value < upper:
            return label
    return "loyal"


@dataclasses.dataclass
class CharacterSheet:
    stats: dict
    mood: int = 0
    mood_word: str = None
    relationships: dict = dataclasses.field(default_factory=dict)
    goals: list = dataclasses.field(default_factory=list)
    conditions: dict = dataclasses.field(default_factory=dict)
    money: int = 0

    # --- dice-facing ---------------------------------------------------------------
    def score(self, stat: str) -> int:
        return int(self.stats.get(stat, 10))

    def mod(self, stat: str) -> int:
        return modifier(self.score(stat))

    def advantage(self, stat: str) -> int:
        """Net advantage (+1) / disadvantage (-1) from current conditions."""
        total = sum(CONDITIONS[c][0].get(stat, 0) for c in self.conditions if c in CONDITIONS)
        return max(-1, min(1, total))

    def attitude(self, name: str) -> int:
        return int(self.relationships.get(name, 0))

    def attitude_label(self, name: str) -> str:
        return attitude_label(self.attitude(name))

    # --- changes ---------------------------------------------------------------------
    def shift_mood(self, delta: int, word: str = None):
        self.mood = max(-3, min(3, self.mood + delta))
        if word:
            self.mood_word = word

    def shift_attitude(self, name: str, delta: int):
        self.relationships[name] = max(-100, min(100, self.attitude(name) + delta))

    def add_condition(self, name: str, ticks: int = None):
        if name in CONDITIONS:
            self.conditions[name] = max(self.conditions.get(name, 0), ticks or CONDITIONS[name][1])

    def set_goals(self, texts: list):
        self.goals = [{"text": t, "progress": 0, "status": "active"} for t in texts]

    def end_tick(self):
        """Conditions wear off; mood drifts one step back toward steady."""
        self.conditions = {c: n - 1 for c, n in self.conditions.items() if n > 1}
        if self.mood:
            self.mood += -1 if self.mood > 0 else 1
            if self.mood == 0:
                self.mood_word = None

    # --- prompt-facing ---------------------------------------------------------------
    def mood_text(self) -> str:
        label = MOOD_LABELS[self.mood]
        return f"{label} ({self.mood_word})" if self.mood_word and self.mood else label

    def stat_line(self) -> str:
        return ", ".join(f"{s} {self.score(s)} ({self.mod(s):+d})" for s in STATS)

    def summary(self, currency: str = "coins", others: list = None) -> str:
        """Two or three lines for a prompt: mood, conditions, money, the
        active goal, and how they feel about whoever is relevant."""
        parts = [f"Mood: {self.mood_text()}."]
        if self.conditions:
            parts.append("Currently " + ", ".join(CONDITIONS[c][2] for c in self.conditions if c in CONDITIONS) + ".")
        parts.append(f"Has {self.money} {currency}.")
        active = next((g for g in self.goals if g["status"] == "active"), None)
        if active:
            parts.append(f"Working toward: {active['text']} ({active['progress']}/3).")
        feelings = [f"{attitude_label(self.attitude(n))} toward {n}" for n in (others or [])
                    if abs(self.attitude(n)) >= 5]
        if feelings:
            parts.append("Feels " + "; ".join(feelings) + ".")
        return " ".join(parts)

    # --- persistence -------------------------------------------------------------------
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterSheet":
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})
