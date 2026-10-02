"""The DM for a SCENE run (agents/world.py's World, when a run has dice &
DM on). It owns every agent's CharacterSheet for the run and does the four
things the run hands it:

- decompose(): a plan item becomes tasks -- {action, stat, difficulty,
  target} -- one per tick, chosen by the model with the sheet in view;
- resolve(): this tick's task is rolled (trivial ones just happen), the
  model narrates the result, the sheet absorbs it, and it becomes a memory;
- perceive() / react() / social(): when two agents meet, a passive Wisdom
  read on the other, a reaction that may be a social move (persuade,
  deceive, intimidate, charm, ask for help, threaten), and the opposed
  check that decides it -- stated in the conversation prompt so the
  dialogue has to honour it;
- end_tick() / save(): conditions wear off, moods settle; sheets are saved
  to the characters at the end.

Dice are seeded per (run seed, agent, tick, purpose), so a run is
reproducible no matter which thread rolls first.
"""

import random
import re
import threading

import theme

from .. import llm
from .. import recorder
from ..gateway import parse_json
from ..textutil import cast_constraint, directive_block
from . import effects, rules
from .sheet import CONDITIONS
from .stats import sheet_from_record

TASK_SCHEMA = {"type": "object", "required": ["tasks"], "properties": {"tasks": {
    "type": "array", "minItems": 1, "items": {"type": "object", "required": ["action", "stat", "difficulty"],
                                              "properties": {"action": {"type": "string"}, "stat": {"type": "string"},
                                                             "difficulty": {"type": "string"},
                                                             "target": {"type": "string"}}}}}}
NARRATION_SCHEMA = {"type": "object", "required": ["narration", "feeling"],
                    "properties": {"narration": {"type": "string"}, "feeling": {"type": "string"}}}
DETAIL_FOR_CONDITION = {"injured": "hurt, favouring one side", "exhausted": "dead on their feet", "drunk": "a little drunk",
                        "shaken": "shaken", "humiliated": "embarrassed about something", "inspired": "unusually sure of themselves",
                        "wanted": "jumpy, like someone's looking for them"}


def ask_json(prompt: str, schema: dict, temperature: float = 0.7):
    """One sync LLM call for a JSON reply, with one repair attempt (SCENE
    has no gateway). None if it never parses."""
    reply = llm.complete(prompt, temperature=temperature)
    data, problem = parse_json(reply, schema)
    if problem is None:
        return data
    reply = llm.chat([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply},
                      {"role": "user", "content": f"That reply was not valid JSON for the format asked ({problem}). "
                                                  "Reply again with ONLY the JSON."}], temperature=0.2)
    data, problem = parse_json(reply, schema)
    return data if problem is None else None


class SceneDM:
    def __init__(self, agents: list, character_ids: dict, seed: int = 0, records: dict = None):
        """`character_ids` {name: char_id} for agents that are saved
        characters (their sheets are loaded and saved); `records` {name:
        character record} to read existing sheets from."""
        self.seed = seed
        self.character_ids = dict(character_ids or {})
        self.sheets = {}
        for a in agents:
            record = (records or {}).get(a.name) or {"id": self.character_ids.get(a.name) or a.name,
                                                     "occupation": a.traits, "bio": a.currently}
            self.sheets[a.name] = sheet_from_record({**record, "occupation": record.get("occupation") or a.traits,
                                                     "bio": record.get("bio") or a.currently},
                                                    seed_key=record.get("id") or a.name)
            a.sheet = self.sheets[a.name]
            a.tasks = []
            a.current_task = None
        self._lock = threading.Lock()

    # --- helpers -----------------------------------------------------------------
    def rng(self, *parts) -> random.Random:
        return random.Random(":".join(str(p) for p in (self.seed, *parts)))

    @staticmethod
    def currency() -> str:
        return (theme.current().get("world") or {}).get("currency", "coins")

    def sheet_block(self, agent, others: list = ()) -> str:
        s = agent.sheet
        return theme.current().prompt("dm.sheet", name=agent.name, stats=s.stat_line(),
                                      summary=s.summary(self.currency(), others=list(others)))

    # --- planning -------------------------------------------------------------------
    def on_plan(self, agent, items: list):
        agent.sheet.set_goals(items)

    def decompose(self, agent, broad_step: str, tick: int, n: int, known_names: list, known_places: list,
                  directive: str, span: str, now_line: str, verbose=False, color=""):
        """(actions, tasks, destination-or-None) for one plan item."""
        t = theme.current()
        places = [p for p in dict.fromkeys(known_places or []) if p]
        where = (" " + t.prompt("dm.decompose_where", name=agent.name, location=agent.location,
                                places="; ".join(places))) if len(places) >= 2 else ""
        schema = TASK_SCHEMA
        if where:
            schema = {**TASK_SCHEMA, "required": ["tasks", "where"],
                      "properties": {**TASK_SCHEMA["properties"], "where": {"type": "string"}}}
        prompt = t.prompt("dm.decompose", identity=agent.identity_summary(),
                          cast_constraint=cast_constraint(agent.name, known_names),
                          directive_block=directive_block(directive), sheet=self.sheet_block(agent, known_names),
                          now_line=now_line, name=agent.name, step=broad_step, n=n, span=span, where=where,
                          where_json=', "where": "..."' if where else "")
        data = ask_json(prompt, schema)
        tasks = []
        for raw in (data or {}).get("tasks", [])[:n]:
            action = str(raw.get("action", "")).strip()
            if action:
                difficulty = str(raw.get("difficulty", "medium")).strip().lower()
                tasks.append({"action": action, "stat": rules.normalise_stat(raw.get("stat")),
                              "difficulty": difficulty if difficulty in rules.DIFFICULTIES else "medium",
                              "target": str(raw.get("target") or "").strip()})
        if not tasks:
            tasks = [{"action": broad_step, "stat": "WIS", "difficulty": "easy", "target": ""}]
        recorder.log("decompose", tick, agent=agent.name, broad_step=broad_step, items=[x["action"] for x in tasks],
                     tasks=tasks)
        agent.memory.add(f"{agent.name} broke '{broad_step}' into: {'; '.join(x['action'] for x in tasks)}",
                         kind="plan", tick=tick, agent_name=agent.name, color=color, verbose=verbose)
        where_raw = (data or {}).get("where")
        return [x["action"] for x in tasks], tasks, where_raw

    # --- resolving a task -------------------------------------------------------------
    def resolve(self, agent, tick: int, clock: str, goal_index: int = None, verbose=False, color=""):
        """Roll this tick's task (unless trivial), narrate it, apply it."""
        task = agent.current_task
        if not task or task["difficulty"] == "trivial":
            return None
        s = agent.sheet
        result = rules.check(s.score(task["stat"]), task["stat"], rules.difficulty_dc(task["difficulty"]),
                             self.rng(agent.name, tick, "task"), advantage=s.advantage(task["stat"]))
        t = theme.current()
        outcome = rules.OUTCOME_WORDS[result.outcome]
        crit = (" -- a critical success, better than anyone could have hoped" if result.outcome == "crit_success" else
                " -- a critical failure, as bad as it could go" if result.outcome == "crit_failure" else "")
        prompt = t.prompt("dm.narrate", identity=agent.identity_summary(), sheet=self.sheet_block(agent),
                          place=agent.location, name=agent.name, action=task["action"],
                          stat_name=rules.STAT_NAMES[task["stat"]], difficulty=task["difficulty"],
                          outcome=f"{outcome.upper()}{crit}", check=result.label(), currency=self.currency(),
                          conditions=", ".join(CONDITIONS))
        data = ask_json(prompt, NARRATION_SCHEMA, temperature=0.8)
        narration = str((data or {}).get("narration") or "").strip() or \
            t.prompt("dm.narrate_fallback", name=agent.name, action=task["action"], outcome=outcome)
        feeling = str((data or {}).get("feeling") or "").strip() or ("pleased" if result.success else "frustrated")
        with self._lock:
            notes = effects.apply_check(s, result, goal_index=goal_index)
            notes += effects.apply_narrated(s, data or {}, critical=result.critical,
                                            about=f"{task['action']} {narration}")
            if result.success and task.get("target") in self.sheets and task["target"] != agent.name:
                self.sheets[task["target"]].shift_attitude(agent.name, 3)
        recorder.log("check", tick, agent=agent.name, action=task["action"], stat=result.stat, roll=result.roll,
                     rolls=result.rolls, mod=result.mod, total=result.total, dc=result.dc, outcome=result.outcome,
                     difficulty=task["difficulty"], text=result.label(), location=agent.location, time=clock)
        recorder.log("outcome", tick, agent=agent.name, text=narration, feeling=feeling, outcome=result.outcome,
                     effects=notes, location=agent.location, time=clock)
        memory = t.prompt("dm.outcome_memory", name=agent.name, action=_lower_first(task["action"]),
                          check=result.label(), narration=narration, feeling=feeling)
        agent.memory.add(memory, kind="observation", tick=tick, importance=8.0 if result.critical else None,
                         agent_name=agent.name, color=color, verbose=verbose)
        return result

    # --- meeting someone -------------------------------------------------------------------
    def perceive(self, observer, target) -> str:
        """A passive Wisdom read (10 + WIS mod) on what shows about the other
        person; "" when there's nothing to see or it isn't seen."""
        s = target.sheet
        visible = [DETAIL_FOR_CONDITION[c] for c in s.conditions if c in DETAIL_FOR_CONDITION]
        if abs(s.mood) >= 2:
            visible.append(s.mood_text())
        if not visible:
            return ""
        passive = 10 + observer.sheet.mod("WIS")
        dc = 12 if len(visible) > 1 or abs(s.mood) >= 3 else 14
        if passive < dc:
            return ""
        return " " + theme.current().prompt("dm.perception", observer=observer.name, target=target.name,
                                            detail=" and ".join(visible[:2]))

    def react(self, agent, other, observation: str, tick: int, known_names: list, directive: str,
              verbose=False, color=""):
        """Like Agent.react, but the agent may answer with a social move.
        Returns (reacted, intent-or-None, topic)."""
        recorder.log("observe", tick, agent=agent.name, text=observation)
        memories = agent.memory.retrieve(observation, tick, k=6)
        t = theme.current()
        memory_text = "\n".join(f"- {m.description}" for m in memories) or t.template("scene.react_no_memories")
        prompt = t.prompt("dm.react", identity=agent.identity_summary(),
                          cast_constraint=cast_constraint(agent.name, known_names),
                          directive_block=directive_block(directive), sheet=self.sheet_block(agent, [other.name]),
                          memories=memory_text, name=agent.name, action=agent.current_action,
                          observation=observation, other=other.name)
        reply = llm.complete(prompt, temperature=0.6)
        agent.memory.add(f"Observed: {observation}", kind="observation", tick=tick,
                         agent_name=agent.name, color=color, verbose=verbose)
        kind, intent, text = parse_react(reply)
        if kind == "talk":
            agent.current_action = f"trying to {intent} {other.name}: {text}" if text else f"trying to {intent} {other.name}"
        elif kind == "react":
            agent.current_action = text
        else:
            recorder.log("continue", tick, agent=agent.name)
            return False, None, ""
        agent.memory.add(f"{agent.name} decided to: {agent.current_action}", kind="observation", tick=tick,
                         agent_name=agent.name, color=color, verbose=verbose)
        recorder.log("react", tick, agent=agent.name, text=agent.current_action, intent=intent)
        return True, intent, text

    def social(self, actor, target, intent: str, tick: int, clock: str) -> str:
        """The opposed check behind a social move; returns the line the
        conversation prompt must honour, and applies the aftermath."""
        stat = effects.SOCIAL_STAT.get(intent, "CHA")
        bonus = target.sheet.attitude(actor.name) // 20   # goodwill helps, grudges hurt
        a, b, won = rules.opposed(actor.sheet.score(stat), stat, target.sheet.score("WIS"), "WIS",
                                  self.rng(actor.name, target.name, tick, "social"),
                                  a_advantage=actor.sheet.advantage(stat), b_advantage=target.sheet.advantage("WIS"),
                                  a_bonus=bonus)
        with self._lock:
            notes = effects.apply_social(actor.sheet, target.sheet, actor.name, target.name, intent, won, a)
            effects.apply_check(actor.sheet, a)
        t = theme.current()
        check = _contest_label(intent, target.name, a, b)
        line = (t.prompt("dm.social_won", actor=actor.name, intent=intent, target=target.name, check=check) if won else
                t.prompt("dm.social_lost", actor=actor.name, intent=intent, target=target.name, check=check,
                         badly=" badly" if a.outcome == "crit_failure" else ""))
        recorder.log("check", tick, agent=actor.name, action=f"{intent} {target.name}", stat=stat, roll=a.roll,
                     rolls=a.rolls, mod=a.mod, total=a.total, dc=b.total + 1, outcome=a.outcome, opposed_by=target.name,
                     opposed_total=b.total, text=_contest_label(intent, target.name, a, b),
                     effects=notes, time=clock)
        result = "it worked" if won else "it failed"
        for who in (actor, target):
            who.memory.add(t.prompt("dm.social_memory", actor=actor.name, intent=intent, target=target.name, result=result),
                           kind="observation", tick=tick, importance=7.0 if a.critical else None, agent_name=who.name)
        return line

    # --- bookkeeping -----------------------------------------------------------------
    def end_tick(self):
        for s in self.sheets.values():
            s.end_tick()

    def save(self, update_character):
        """Write each saved character's sheet back (update_character(id, sheet=...))."""
        for name, char_id in self.character_ids.items():
            if char_id and name in self.sheets:
                try:
                    update_character(char_id, sheet=self.sheets[name].to_dict())
                except Exception:
                    pass

    def snapshot(self) -> dict:
        return {name: s.to_dict() for name, s in self.sheets.items()}


def _contest_label(intent: str, target: str, a, b) -> str:
    """"persuade Sal: CHA 7+2=9 vs WIS 12 -- failure" (with adv/disadv)."""
    bonus = a.mod + a.bonus
    adv = " (adv)" if a.advantage > 0 else " (disadv)" if a.advantage < 0 else ""
    return (f"{intent} {target}: {a.stat} {a.roll}{'+' if bonus >= 0 else '-'}{abs(bonus)}={a.total} vs WIS {b.total}"
            f"{adv} -- {rules.OUTCOME_WORDS[a.outcome]}")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def parse_react(reply: str):
    """("talk", intent, text) | ("react", None, text) | ("continue", None, "")."""
    for line in (reply or "").splitlines():
        line = line.strip().strip("*").strip()
        m = re.match(r"^TALK\s*\(?\s*([a-z ]+?)\s*\)?\s*:\s*(.*)$", line, re.IGNORECASE)
        if m:
            intent = m.group(1).strip().lower()
            intent = next((i for i in effects.SOCIAL_INTENTS if i == intent or intent.startswith(i)), "persuade")
            return "talk", intent, m.group(2).strip()
        if re.match(r"^TALK\b", line, re.IGNORECASE):
            return "talk", "persuade", line.split(":", 1)[1].strip() if ":" in line else ""
        if line.upper().startswith("REACT"):
            text = line.split(":", 1)[1].strip() if ":" in line else ""
            return ("react", None, text) if text else ("continue", None, "")
        if line.upper().startswith("CONTINUE"):
            return "continue", None, ""
    return "continue", None, ""

