"""What a check does to the people involved. Fixed tables -- the narrator
may add one small, validated effect (money changing hands, one condition),
never anything else."""

from .sheet import CONDITIONS, CharacterSheet

# outcome -> (mood shift, mood word)
MOOD = {"crit_success": (2, "triumphant"), "success": (1, "satisfied"),
        "failure": (-1, "frustrated"), "crit_failure": (-2, "rattled")}
# what a critical failure on a stat leaves behind
CRIT_FAIL_CONDITION = {"STR": "injured", "DEX": "injured", "CON": "exhausted",
                       "INT": "shaken", "WIS": "shaken", "CHA": "humiliated"}
MONEY_LIMIT = 200          # the most a single narrated effect can move
SOCIAL_INTENTS = ("persuade", "deceive", "intimidate", "charm", "ask for help", "threaten")
# intent -> (target's attitude shift toward the actor on a win, on a loss)
SOCIAL_ATTITUDE = {"persuade": (12, -4), "charm": (15, -6), "ask for help": (10, -3),
                   "deceive": (6, -25), "intimidate": (-8, -15), "threaten": (-15, -20)}
SOCIAL_STAT = {"persuade": "CHA", "charm": "CHA", "ask for help": "CHA", "deceive": "CHA",
               "intimidate": "CHA", "threaten": "STR"}


def apply_check(sheet: CharacterSheet, result, goal_index: int = None) -> list:
    """Mood, goal progress and crit conditions from one check. Returns
    short notes on what changed (for the log)."""
    notes = []
    delta, word = MOOD[result.outcome]
    sheet.shift_mood(delta, word)
    if goal_index is not None and 0 <= goal_index < len(sheet.goals):
        goal = sheet.goals[goal_index]
        if goal["status"] == "active":
            if result.success:
                goal["progress"] = min(3, goal["progress"] + (2 if result.outcome == "crit_success" else 1))
                if goal["progress"] >= 3:
                    goal["status"] = "achieved"
                    sheet.shift_mood(1, "accomplished")
                    notes.append(f"achieved: {goal['text']}")
            elif result.outcome == "crit_failure":
                goal["progress"] = max(0, goal["progress"] - 1)
    if result.outcome == "crit_failure":
        condition = CRIT_FAIL_CONDITION[result.stat]
        sheet.add_condition(condition)
        notes.append(condition)
    if result.outcome == "crit_success":
        sheet.add_condition("inspired")
        notes.append("inspired")
    return notes


def apply_narrated(sheet: CharacterSheet, effect: dict) -> list:
    """The narrator's optional effect, validated and clamped: money in
    [-MONEY_LIMIT, MONEY_LIMIT] (never below zero), one known condition."""
    notes = []
    if not isinstance(effect, dict):
        return notes
    money = effect.get("money")
    if isinstance(money, (int, float)) and money:
        change = int(max(-MONEY_LIMIT, min(MONEY_LIMIT, money)))
        change = max(change, -sheet.money)
        if change:
            sheet.money += change
            notes.append(f"{change:+d} money")
    condition = str(effect.get("condition") or "").strip().lower()
    if condition in CONDITIONS:
        sheet.add_condition(condition)
        notes.append(condition)
    return notes


def apply_social(actor: CharacterSheet, target: CharacterSheet, actor_name: str, target_name: str,
                 intent: str, actor_won: bool, actor_result=None) -> list:
    """A social contest's aftermath: the target's attitude toward the actor
    (and a little the other way), both moods."""
    gain, loss = SOCIAL_ATTITUDE.get(intent, (8, -5))
    if target is not None:
        target.shift_attitude(actor_name, gain if actor_won else loss)
        if intent in ("intimidate", "threaten") and actor_won:
            target.shift_mood(-1, "intimidated")
    actor.shift_attitude(target_name, 4 if actor_won else -6)
    notes = []
    if actor_result is not None and actor_result.outcome == "crit_failure":
        actor.add_condition("humiliated")
        notes.append("humiliated")
    return notes
