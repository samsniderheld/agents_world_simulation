"""CITY-mode prompt builders, schemas and parsers. The prompt text itself is
the current theme's `prompts.city` section (theme.py); this module fills it.

Every prompt is built as four parts, in this order, so a server with prefix
caching can reuse the KV cache across a batch (agents/gateway.py sorts each
batch by these):

    [shared city/era/rules prefix] [tier instructions] [identity] [this call]

The shared prefix and tier instructions are identical for every call of a
tier in a run; the identity is identical for every call one agent makes.
"""

import re

import theme

from ..textutil import directive_block, parse_list_lines
from . import config as ccfg


def _t():
    return theme.current()


def __getattr__(name):
    """HERO_TIER / BACKGROUND_TIER / NARRATOR_TIER: the current theme's tier
    instructions (module attributes, so callers read them like constants)."""
    keys = {"HERO_TIER": "city.hero_tier", "BACKGROUND_TIER": "city.background_tier",
            "NARRATOR_TIER": "city.narrator_tier"}
    if name in keys:
        return _t().template(keys[name])
    if name == "YEAR":
        return _t().present_year
    raise AttributeError(name)


# --- The four parts ----------------------------------------------------------------------

def city_prefix(city: dict) -> str:
    """Shared by every CITY call in a run: the setting and the rules."""
    summary = (city or {}).get("summary") or ""
    if len(summary) > 600:
        summary = summary[:600].rsplit(" ", 1)[0] + "..."
    t = _t()
    history = (t.prompt("city.prefix_history", summary=summary) + "\n") if summary else ""
    return t.prompt("city.prefix", present_year=t.present_year, history=history)


def city_report(header: str, lines: list, previous: str = None) -> str:
    """A briefing on the run so far (agents/city/insight.py)."""
    t = _t()
    earlier = ("\n" + t.prompt("city.report_previous", briefing=previous.strip()) + "\n"
               if previous and previous.strip() else "")
    return t.prompt("city.report", header=header, log="\n".join(lines), previous=earlier,
                    changes=(t.prompt("city.report_changes") + "\n") if earlier else "")


def city_question(header: str, lines: list, question: str) -> str:
    """A question about the run, answered from the log (agents/city/insight.py)."""
    return _t().prompt("city.question", header=header, log="\n".join(lines), question=question)


def hero_identity(hero) -> str:
    return hero.identity_summary()


def background_identity(b) -> str:
    return _t().prompt("city.background_identity", name=b.name, age=b.age, occupation=b.occupation, bio=b.bio,
                       location=b.location_label())


# --- The cast constraint -------------------------------------------------------------------

def cast_line(speaker: str, names: list) -> str:
    """CITY's version of textutil.cast_constraint: the same no-invented-
    names rule, but naming only the people relevant to this call
    (co-located agents, the listener, relationships) instead of every
    agent in the run -- a thousand names would drown the prompt."""
    others = [n for n in dict.fromkeys(names or []) if n and n != speaker]
    if others:
        return _t().prompt("city.cast_line", name=speaker, names=", ".join(others))
    return _t().prompt("city.cast_line_empty", name=speaker)


# --- Directive -------------------------------------------------------------------------------

def directive_for_background(directive: str, agent) -> str:
    """The directive applies to heroes always, and to a background agent
    only when it explicitly involves them: it names them, their
    occupation, or everyone (the theme's city_life.everyone_words)."""
    if not directive:
        return None
    text = directive.lower()
    first = agent.name.split()[0].lower()
    if (agent.name.lower() in text or re.search(rf"\b{re.escape(first)}\b", text)
            or (agent.occupation and agent.occupation.lower() in text)
            or any(k in text for k in _t()["city_life"]["everyone_words"])):
        return directive
    return None


# --- Calls: heroes ---------------------------------------------------------------------------

def plan_schema(n: int) -> dict:
    return {"type": "object", "required": ["items"],
            "properties": {"items": {"type": "array", "minItems": n, "maxItems": n, "items": {"type": "string"}}}}


def hero_plan(hero, memories: list, cast: list, directive: str, horizon: str, per_item: str,
              n_items: int, now: str, until: str) -> str:
    t = _t()
    memory_text = "\n".join(f"- {m}" for m in memories) or t.template("city.plan_no_memories")
    return t.prompt("city.plan", cast_line=cast_line(hero.name, cast), directive_block=directive_block(directive),
                    name=hero.name, memories=memory_text, currently=hero.currently, horizon=horizon, now=now,
                    until=until, n_items=n_items, per_item=per_item)


def decompose_schema(n: int, places: list) -> dict:
    props = {"actions": {"type": "array", "minItems": 1, "maxItems": n, "items": {"type": "string"}}}
    required = ["actions"]
    if places:
        props["where"] = {"type": "string", "enum": list(places) + ["STAY"]}
        required.append("where")
    return {"type": "object", "required": required, "properties": props}


def hero_decompose(hero, broad_step: str, n: int, span: str, cast: list, directive: str,
                   now: str, places: list) -> str:
    t = _t()
    where = (" " + t.prompt("city.decompose_where", name=hero.name, location=hero.location,
                            places="; ".join(places))) if places else ""
    return t.prompt("city.decompose", cast_line=cast_line(hero.name, cast), directive_block=directive_block(directive),
                    now=now, name=hero.name, step=broad_step, n=n, span=span, where=where,
                    where_json=', "where": "..."' if places else "")


def hero_react(hero, other_name: str, other_doing: str, memories: list, cast: list,
               directive: str) -> str:
    t = _t()
    memory_text = "\n".join(f"- {m}" for m in memories) or t.template("city.react_no_memories")
    return t.prompt("city.react", cast_line=cast_line(hero.name, cast), directive_block=directive_block(directive),
                    memories=memory_text, name=hero.name, action=hero.current_action, other=other_name,
                    other_doing=other_doing)


def parse_react(reply: str):
    """("talk" | "react" | "continue", text). Reads the first line that
    starts with one of the three tags; anything else is CONTINUE -- a
    CITY-only parser (SCENE keeps world._DIALOGUE_HINTS)."""
    for line in (reply or "").splitlines():
        m = re.match(r"^\s*[*\"']*\s*(TALK|REACT|CONTINUE)\b\s*[:\-]?\s*(.*)$", line.strip(), re.IGNORECASE)
        if m:
            tag, text = m.group(1).lower(), m.group(2).strip().strip('"*').strip()
            if tag != "continue" and not text:
                return ("continue", "")
            return (tag, text)
    return ("continue", "")


def dialogue_line(speaker_is_hero: bool, speaker, listener_name: str, place: str, topic: str,
                  memories: list, transcript: list, cast: list, directive: str, turn: int,
                  max_turns: int) -> str:
    """One turn of a conversation run in lockstep (every conversation in
    the city advances one line per batch). A background speaker gets the
    same shape with fewer memories -- the tier prefix already tells the
    model to keep them plain."""
    t = _t()
    memory_text = "\n".join(f"- {m}" for m in memories) or t.template("city.dialogue_no_memories")
    so_far = "\n".join(transcript) or t.template("city.dialogue_nobody_yet")
    opener = (t.prompt("city.dialogue_opener", name=speaker.name, topic=topic) + "\n"
              if topic and not transcript else "")
    return t.prompt(
        "city.dialogue", cast_line=cast_line(speaker.name, cast),
        directive_block=directive_block(directive) if speaker_is_hero else "", name=speaker.name,
        listener=listener_name, place=place, memories=memory_text, opener=opener, transcript=so_far,
        end_hint=t.prompt("city.dialogue_end_hint", end_marker=ccfg.END_MARKER) if turn >= 2 else "",
        last_turn=(" " + t.prompt("city.dialogue_last_turn", turn=turn + 1, max_turns=max_turns))
        if turn == max_turns - 1 else "")


def parse_line(reply: str, speaker_name: str):
    """The spoken line, or None for the [END] marker / an empty reply."""
    text = (reply or "").strip()
    if not text or ccfg.END_MARKER.lower() in text.lower()[:12]:
        return None
    line = text.splitlines()[0].strip()
    first = speaker_name.split()[0].lower()
    label, _, rest = line.partition(":")
    if rest and (label.strip().strip('*"').lower() in (speaker_name.lower(), first) or len(label) < 30 and first in label.lower()):
        line = rest
    line = re.sub(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*", "", line).strip().strip('"').strip()
    return line or None


def importance_schema(n: int) -> dict:
    return {"type": "object", "required": ["ratings"],
            "properties": {"ratings": {"type": "array", "minItems": n, "maxItems": n,
                                       "items": {"type": "integer"}}}}


def importance(descriptions: list) -> str:
    """The same scale as SCENE's memory._rate_importance_batch, as JSON."""
    listing = "\n".join(f"{i}. {d}" for i, d in enumerate(descriptions, 1))
    return _t().prompt("city.importance", items=listing, count=len(descriptions))


FOCAL_SCHEMA = {"type": "object", "required": ["questions"],
                "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string"}}}}


def focal_points(hero, statements: list, n: int) -> str:
    listing = "\n".join(f"- {s}" for s in statements)
    return _t().prompt("city.focal_points", name=hero.name, statements=listing, n=n)


INSIGHT_SCHEMA = {"type": "object", "required": ["insights"], "properties": {"insights": {
    "type": "array", "minItems": 1, "maxItems": 5, "items": {
        "type": "object", "required": ["text", "because"],
        "properties": {"text": {"type": "string"}, "because": {"type": "array", "items": {"type": "integer"}}}}}}}


def insights(hero, focal: str, statements: list, n: int) -> str:
    listing = "\n".join(f"{i}. {s}" for i, s in enumerate(statements))
    return _t().prompt("city.insights", name=hero.name, statements=listing, n=n, focal=focal)


# --- Calls: background -----------------------------------------------------------------------

def schedule_schema(places: list) -> dict:
    return {"type": "object", "required": ["schedule"], "properties": {"schedule": {
        "type": "array", "minItems": 3, "maxItems": 8, "items": {
            "type": "object", "required": ["start", "end", "activity", "place"],
            "properties": {"start": {"type": "string"}, "end": {"type": "string"},
                           "activity": {"type": "string"},
                           "place": {"type": "string", "enum": list(places)}}}}}}


def background_schedule(b, places: list, day_label: str, directive: str) -> str:
    return _t().prompt("city.schedule", directive_block=directive_block(directive), name=b.name, day=day_label,
                       places="; ".join(places), work=b.work or "no fixed place", haunt=b.haunt or "home")


def bio_upgrade(b, place: str) -> str:
    t = _t()
    return t.prompt("city.bio_upgrade", name=b.name, age=b.age, occupation=b.occupation, present_year=t.present_year,
                    bio=b.bio, work=b.work or "no fixed workplace", haunt=b.haunt or "home", place=place)


def split_list(text: str) -> list:
    return parse_list_lines(text)


# --- A plausible stub replier (benchmark / tests) ---------------------------------------------

def stub_reply(prompt: str, schema):
    """What agents/city/stub_server.StubServer answers with in the
    benchmark: JSON calls get a valid instance with sensible values;
    react/dialogue calls get the tags and lines the parsers expect. Cheap
    and deterministic in the prompt."""
    import hashlib
    import json
    from .stub_server import instance_of
    h = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16)
    if schema is not None:
        props = schema.get("properties", {})
        if "schedule" in props:
            places = props["schedule"]["items"]["properties"]["place"]["enum"]
            blocks, start = [], 0
            for k, end in enumerate((7 * 60, 12 * 60, 13 * 60, 18 * 60, 22 * 60, 24 * 60)):
                place = places[(h >> k) % len(places)] if 0 < k < 5 else "home"
                blocks.append({"start": f"{start // 60:02d}:{start % 60:02d}",
                               "end": f"{end // 60 % 24:02d}:{end % 60:02d}" if end < 1440 else "23:59",
                               "activity": f"routine {k}", "place": place})
                start = end
            return json.dumps({"schedule": blocks})
        if "ratings" in props:
            n = props["ratings"]["minItems"]
            return json.dumps({"ratings": [1 + (h >> i) % 9 for i in range(n)]})
        if "where" in props:
            n = props["actions"]["maxItems"]
            enum = props["where"]["enum"]
            return json.dumps({"actions": [f"step {k} {h % 97}" for k in range(n)],
                               "where": enum[h % len(enum)] if h % 3 == 0 else "STAY"})
        return json.dumps(instance_of(schema, h))
    if "TALK: <" in prompt:
        return ["TALK: the job at the docks", "REACT: steps outside for air", "CONTINUE"][h % 3]
    if "next line" in prompt:
        return ccfg.END_MARKER if ("turn" in prompt and h % 4 == 0) else f"You hear about the {h % 50} grand? Keep it quiet."
    if "QUIRK:" in prompt:
        return "A tired, careful person with a past. Wears a grey coat.\nQUIRK: counts coins twice"
    return f"A plain reply {h % 1000}."
