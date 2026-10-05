"""The DM for a CITY run (agents/city/world.py's CityWorld, when a run has
dice & DM on). The same rules as SCENE's (agents/dm/scene.py) -- tasks,
code-rolled checks, LLM narration, perception and opposed social checks --
but shaped for waves: this builds prompts and applies replies, and the
world batches the calls through the gateway. Background residents roll too,
with no LLM at all (agents/dm/background.py).

Sheets are keyed by name (unique across both tiers in a run), so a resident
promoted to hero mid-run keeps theirs.
"""

import collections
import random

import theme

from ..textutil import directive_block
from . import background as bg_dice
from . import effects, rules
from .scene import DETAIL_FOR_CONDITION, _contest_label, _lower_first
from .sheet import CONDITIONS, currency
from .stats import sheet_from_record

NARRATION_SCHEMA = {"type": "object", "required": ["narration", "feeling", "money", "condition"],
                    "properties": {"narration": {"type": "string"}, "feeling": {"type": "string"},
                                   "money": {"type": "integer"}, "condition": {"type": "string"}}}


def task_schema(n: int, places: list) -> dict:
    item = {"type": "object", "required": ["action", "stat", "difficulty", "target"],
            "properties": {"action": {"type": "string"}, "stat": {"type": "string", "enum": list(rules.STATS)},
                           "difficulty": {"type": "string", "enum": list(rules.DIFFICULTIES)},
                           "target": {"type": "string"}}}
    props = {"tasks": {"type": "array", "minItems": 1, "maxItems": n, "items": item}}
    required = ["tasks"]
    if places:
        props["where"] = {"type": "string", "enum": list(places) + ["STAY"]}
        required.append("where")
    return {"type": "object", "required": required, "properties": props}


class CityDM:
    def __init__(self, seed: int = 0, records: dict = None):
        """`records` {name: character record} for heroes who are saved
        characters (their sheets are read from it); background residents
        carry their own record."""
        self.seed = seed
        self.records = dict(records or {})
        self.sheets = {}
        self.tick_counts = collections.Counter()

    # --- helpers ---------------------------------------------------------------------
    def rng(self, *parts) -> random.Random:
        return random.Random(":".join(str(p) for p in (self.seed, *parts)))

    @staticmethod
    def currency() -> str:
        return currency()

    def sheet(self, agent):
        """The agent's sheet, loaded or rolled the first time it's needed."""
        s = self.sheets.get(agent.name)
        if s is None:
            if agent.tier == "hero":
                record = self.records.get(agent.name) or {}
                record = {**record, "occupation": record.get("occupation") or agent.traits,
                          "bio": record.get("bio") or agent.currently}
                key = record.get("id") or getattr(agent, "promoted_from", None) or agent.name
            else:
                record, key = agent.record, agent.id
            s = self.sheets[agent.name] = sheet_from_record(record, seed_key=key)
        agent.sheet = s
        return s

    def sheet_block(self, agent, others: list = ()) -> str:
        s = self.sheet(agent)
        return theme.current().prompt("dm.sheet", name=agent.name, stats=s.stat_line(),
                                      summary=s.summary(self.currency(), others=list(others)))

    @staticmethod
    def remember(agent, text: str, tick: int, importance: float = None, with_hero: bool = False):
        if agent.tier == "hero":
            agent.memory.queue_add(text, "observation", tick, importance=importance)
        else:
            agent.memory.add(tick, "outcome", text, with_hero=with_hero)

    # --- planning ------------------------------------------------------------------------
    def on_plan(self, hero, items: list):
        self.sheet(hero).set_goals(items)

    def decompose_prompt(self, hero, step: str, n: int, span: str, cast: list, directive: str,
                         now: str, places: list) -> str:
        from ..city.prompts import cast_line
        t = theme.current()
        where = (" " + t.prompt("dm.decompose_where", name=hero.name, location=hero.location,
                                places="; ".join(places))) if places else ""
        return t.prompt("dm.decompose", identity="", cast_constraint=cast_line(hero.name, cast),
                        directive_block=directive_block(directive), sheet=self.sheet_block(hero, cast),
                        now_line=t.prompt("scene.now", now=now) + " ", name=hero.name, step=step, n=n, span=span,
                        where=where, where_json=', "where": "..."' if places else "").strip()

    @staticmethod
    def parse_tasks(data, step: str, n: int) -> list:
        tasks = []
        for raw in (data or {}).get("tasks", [])[:n]:
            if not isinstance(raw, dict):
                continue
            action = str(raw.get("action", "")).strip()
            if action:
                difficulty = str(raw.get("difficulty", "medium")).strip().lower()
                tasks.append({"action": action, "stat": rules.normalise_stat(raw.get("stat")),
                              "difficulty": difficulty if difficulty in rules.DIFFICULTIES else "medium",
                              "target": str(raw.get("target") or "").strip()})
        return tasks or [{"action": step, "stat": "WIS", "difficulty": "easy", "target": ""}]

    # --- RESOLVE ---------------------------------------------------------------------------
    def roll(self, hero, tick: int):
        """This tick's check for a hero's task (None if there's nothing to roll)."""
        task = getattr(hero, "current_task", None)
        if not task or task["difficulty"] == "trivial":
            return None
        s = self.sheet(hero)
        return rules.check(s.score(task["stat"]), task["stat"], rules.difficulty_dc(task["difficulty"]),
                           self.rng(hero.name, tick, "task"), advantage=s.advantage(task["stat"]))

    def narrate_prompt(self, hero, task: dict, result) -> str:
        outcome = rules.OUTCOME_WORDS[result.outcome]
        crit = (" -- a critical success, better than anyone could have hoped" if result.outcome == "crit_success" else
                " -- a critical failure, as bad as it could go" if result.outcome == "crit_failure" else "")
        return theme.current().prompt(
            "dm.narrate", identity="", sheet=self.sheet_block(hero), place=hero.location, name=hero.name,
            action=task["action"], stat_name=rules.STAT_NAMES[task["stat"]], difficulty=task["difficulty"],
            outcome=f"{outcome.upper()}{crit}", check=result.label(), currency=self.currency(),
            conditions=", ".join(CONDITIONS)).strip()

    def apply_resolution(self, hero, task: dict, result, data, tick: int, clock: str, log, by_name: dict):
        """The narrated result: sheet effects, check/outcome events, a memory."""
        t = theme.current()
        outcome = rules.OUTCOME_WORDS[result.outcome]
        narration = str((data or {}).get("narration") or "").strip() or \
            t.prompt("dm.narrate_fallback", name=hero.name, action=task["action"], outcome=outcome)
        feeling = str((data or {}).get("feeling") or "").strip() or ("pleased" if result.success else "frustrated")
        s = self.sheet(hero)
        notes = effects.apply_check(s, result, goal_index=hero.current_item)
        notes += effects.apply_narrated(s, data or {}, critical=result.critical, about=f"{task['action']} {narration}")
        target = by_name.get(task.get("target"))
        if result.success and target is not None and target is not hero:
            self.sheet(target).shift_attitude(hero.name, 3)
        self.tick_counts["checks"] += 1
        self.tick_counts["hero_checks"] += 1
        log("check", hero, action=task["action"], stat=result.stat, roll=result.roll, rolls=result.rolls,
            mod=result.mod, total=result.total, dc=result.dc, outcome=result.outcome, difficulty=task["difficulty"],
            text=result.label(), location=hero.location, time=clock)
        log("outcome", hero, action=task["action"], text=narration, feeling=feeling, outcome=result.outcome,
            effects=notes, location=hero.location, time=clock)
        self.remember(hero, t.prompt("dm.outcome_memory", name=hero.name, action=_lower_first(task["action"]),
                                     check=result.label(), narration=narration, feeling=feeling),
                      tick, importance=8.0 if result.critical else None)

    # --- meeting someone -----------------------------------------------------------------------
    def perceive(self, observer, target) -> str:
        """A passive Wisdom read on what shows about the other person."""
        s = self.sheet(target)
        visible = [DETAIL_FOR_CONDITION[c] for c in s.conditions if c in DETAIL_FOR_CONDITION]
        if abs(s.mood) >= 2:
            visible.append(s.mood_text())
        if not visible:
            return ""
        dc = 12 if len(visible) > 1 or abs(s.mood) >= 3 else 14
        if 10 + self.sheet(observer).mod("WIS") < dc:
            return ""
        return " " + theme.current().prompt("dm.perception", observer=observer.name, target=target.name,
                                            detail=" and ".join(visible[:2]))

    def react_prompt(self, hero, other, observation: str, memories: list, cast: list, directive: str) -> str:
        from ..city.prompts import cast_line
        t = theme.current()
        memory_text = "\n".join(f"- {m}" for m in memories) or t.template("city.react_no_memories")
        return t.prompt("dm.react", identity="", cast_constraint=cast_line(hero.name, cast), directive_block=directive_block(directive),
                        sheet=self.sheet_block(hero, [other.name]), memories=memory_text, name=hero.name,
                        action=hero.current_action, observation=observation, other=other.name).strip()

    def social(self, actor, target, intent: str, tick: int, clock: str, log) -> str:
        """The opposed check behind a social move: applies the aftermath and
        returns the ruling every line of the conversation must honour."""
        a_sheet, b_sheet = self.sheet(actor), self.sheet(target)
        stat = effects.SOCIAL_STAT.get(intent, "CHA")
        a, b, won = rules.opposed(a_sheet.score(stat), stat, b_sheet.score("WIS"), "WIS",
                                  self.rng(actor.name, target.name, tick, "social"),
                                  a_advantage=a_sheet.advantage(stat), b_advantage=b_sheet.advantage("WIS"),
                                  a_bonus=b_sheet.attitude(actor.name) // 20)
        notes = effects.apply_social(a_sheet, b_sheet, actor.name, target.name, intent, won, a)
        effects.apply_check(a_sheet, a)
        self.tick_counts["checks"] += 1
        self.tick_counts["social_checks"] += 1
        t = theme.current()
        check = _contest_label(intent, target.name, a, b)
        log("check", actor, action=f"{intent} {target.name}", stat=stat, roll=a.roll, rolls=a.rolls, mod=a.mod,
            total=a.total, dc=b.total + 1, outcome=a.outcome, opposed_by=target.name, opposed_total=b.total,
            text=check, effects=notes, location=actor.location, time=clock)
        memory = t.prompt("dm.social_memory", actor=actor.name, intent=intent, target=target.name,
                          result="it worked" if won else "it failed")
        for who in (actor, target):
            self.remember(who, memory, tick, importance=7.0 if a.critical else None, with_hero=True)
        if won:
            return t.prompt("dm.social_won", actor=actor.name, intent=intent, target=target.name, check=check)
        return t.prompt("dm.social_lost", actor=actor.name, intent=intent, target=target.name, check=check,
                        badly=" badly" if a.outcome == "crit_failure" else "")

    # --- background residents ---------------------------------------------------------------------
    def background_block(self, b, activity: str, where: str, tick: int):
        """A resident starting a schedule block rolls for it (no LLM); the
        outcome goes into their ring memory. Returns the outcome or None."""
        out = bg_dice.roll_block(b, self.sheet(b), activity, where, self.rng(b.id, tick, "block"))
        if out is None:
            return None
        self.tick_counts["checks"] += 1
        self.tick_counts["background_checks"] += 1
        self.tick_counts[out["result"].outcome] += 1
        b.memory.add(tick, "outcome", out["text"])
        return out

    # --- bookkeeping ---------------------------------------------------------------------------------
    def take_counts(self) -> dict:
        counts, self.tick_counts = dict(self.tick_counts), collections.Counter()
        return counts

    def end_tick(self):
        for s in self.sheets.values():
            s.end_tick()

    def save(self, storage, heroes: list, background: list):
        """Write sheets back: saved characters via update_character_fields,
        background residents (and residents promoted this run) into the
        city's background list in one write."""
        for h in heroes:
            if h.character_id and h.name in self.sheets and hasattr(storage, "update_character_fields"):
                try:
                    storage.update_character_fields(h.character_id, sheet=self.sheets[h.name].to_dict())
                except Exception:
                    pass
        by_id = {b.id: self.sheets[b.name] for b in background if b.name in self.sheets}
        by_id.update({h.promoted_from: self.sheets[h.name] for h in heroes
                      if getattr(h, "promoted_from", None) and h.name in self.sheets})
        if not by_id:
            return 0
        residents = list(storage.get_background() or [])
        changed = 0
        for r in residents:
            s = by_id.get(r.get("id"))
            if s is not None:
                r["sheet"] = s.to_dict()
                changed += 1
        if changed:
            storage.save_background(residents)
        return changed

