"""CITY-mode prompts, schemas and parsers. SCENE mode's prompts (planning.py,
agent.py, reflection.py, memory.py, world.py) are left exactly as they are;
where CITY needs a different prompt or parser, it lives here.

Every prompt is built as four parts, in this order, so a server with prefix
caching can reuse the KV cache across a batch (agents/gateway.py sorts each
batch by these):

    [shared city/era/rules prefix] [tier instructions] [identity] [this call]

The shared prefix and tier instructions are identical for every call of a
tier in a run; the identity is identical for every call one agent makes.
"""

import re

from ..textutil import directive_block, parse_list_lines
from . import config as ccfg

YEAR = 1959


# --- The four parts ----------------------------------------------------------------------

def city_prefix(city: dict) -> str:
    """Shared by every CITY call in a run: the setting and the rules."""
    summary = (city or {}).get("summary") or ""
    if len(summary) > 600:
        summary = summary[:600].rsplit(" ", 1)[0] + "..."
    return (
        f"This is a simulation of a city: an alternate-history New York City in {YEAR}, "
        "a film-noir world of rain-slick streets, smoke-filled bars, cops on the take and "
        "people keeping secrets. Everything happens in 1959: no anachronisms, nothing "
        "supernatural.\n"
        + (f"The city's history, briefly: {summary}\n" if summary else "")
        + "Rules for every reply: only people named in the prompt exist -- never invent or "
        "name anyone else; refer to anyone else generically ('the bartender', 'a cop'). "
        "Answer in exactly the format asked for, with nothing before or after it."
    )


HERO_TIER = (
    "You are writing for one of the story's main characters. Be specific, stay true to "
    "their personality and memories, and keep each answer short."
)

BACKGROUND_TIER = (
    "You are writing for a minor resident of the city. Keep it brief, plain and "
    "routine -- ordinary life, not drama."
)


NARRATOR_TIER = (
    "You are the city's observer: you read what the simulation recorded and explain it plainly and "
    "accurately. Use only what the log shows -- never invent events, motives or people; say when the "
    "log doesn't tell you."
)


def city_report(header: str, lines: list, previous: str = None) -> str:
    """A briefing on the run so far (agents/city/insight.py)."""
    earlier = (f"\nYour previous briefing, for comparison -- focus on what has changed since:\n{previous.strip()}\n"
               if previous and previous.strip() else "")
    return (
        f"{header}\n\nThe run's log (oldest first; it may start mid-run):\n" + "\n".join(lines) + "\n"
        f"{earlier}\n"
        "Write a short briefing on what is going on in the city, under these headings:\n"
        "STORYLINES: the 2-5 main threads, each one or two sentences naming who is involved and where.\n"
        "PLACES: where the crowds and the tension are.\n"
        "PEOPLE TO WATCH: residents becoming important, and why.\n"
        + ("CHANGES: what is new since the previous briefing.\n" if earlier else "")
        + "Be concrete and brief; plain text, no markdown."
    )


def city_question(header: str, lines: list, question: str) -> str:
    """A question about the run, answered from the log (agents/city/insight.py)."""
    return (
        f"{header}\n\nWhat the run's log says that may be relevant (oldest first):\n" + "\n".join(lines) + "\n\n"
        f"Question: {question}\n\n"
        "Answer in a few sentences from the log alone, naming who said or did what, and when and where. "
        "If the log doesn't answer it, say so and say what it does show. Plain text."
    )


def hero_identity(hero) -> str:
    return hero.identity_summary()


def background_identity(b) -> str:
    return (f"{b.name}, {b.age}, {b.occupation}. {b.bio} "
            f"Right now, {b.name} is at {b.location_label()}.")


# --- The cast constraint -------------------------------------------------------------------

def cast_line(speaker: str, names: list) -> str:
    """CITY's version of textutil.cast_constraint: the same no-invented-
    names rule, but naming only the people relevant to this call
    (co-located agents, the listener, relationships) instead of every
    agent in the run -- a thousand names would drown the prompt."""
    others = [n for n in dict.fromkeys(names or []) if n and n != speaker]
    if others:
        return (f"People {speaker} might name here: {', '.join(others)}. Do not invent or name "
                "any other person; refer to anyone else only generically.")
    return f"{speaker} should not name anyone -- refer to other people only generically."


# --- Directive -------------------------------------------------------------------------------

_EVERYONE = ("everyone", "everybody", "the whole city", "all residents", "background", "the crowd",
             "all the residents", "citywide", "city-wide")


def directive_for_background(directive: str, agent) -> str:
    """The directive applies to heroes always, and to a background agent
    only when it explicitly involves them: it names them, their
    occupation, or everyone."""
    if not directive:
        return None
    text = directive.lower()
    first = agent.name.split()[0].lower()
    if (agent.name.lower() in text or re.search(rf"\b{re.escape(first)}\b", text)
            or (agent.occupation and agent.occupation.lower() in text)
            or any(k in text for k in _EVERYONE)):
        return directive
    return None


# --- Calls: heroes ---------------------------------------------------------------------------

def plan_schema(n: int) -> dict:
    return {"type": "object", "required": ["items"],
            "properties": {"items": {"type": "array", "minItems": n, "maxItems": n, "items": {"type": "string"}}}}


def hero_plan(hero, memories: list, cast: list, directive: str, horizon: str, per_item: str,
              n_items: int, now: str, until: str) -> str:
    memory_text = "\n".join(f"- {m}" for m in memories) or "(no memories yet)"
    return (
        f"{cast_line(hero.name, cast)}\n{directive_block(directive)}\n"
        f"What {hero.name} remembers from before -- context only, not a template to repeat:\n{memory_text}\n\n"
        f"{hero.name} typically starts the day around: {hero.currently}.\n"
        f"Plan what {hero.name} is trying to do over the next {horizon}, from {now} until {until}: "
        "their goals for that stretch and what they'll actually spend it on, moving their story forward.\n"
        f"Give exactly {n_items} items in order, each covering about {per_item}; each a short phrase, no times. "
        'Reply as JSON: {"items": ["...", ...]}'
    )


def decompose_schema(n: int, places: list) -> dict:
    props = {"actions": {"type": "array", "minItems": 1, "maxItems": n, "items": {"type": "string"}}}
    required = ["actions"]
    if places:
        props["where"] = {"type": "string", "enum": list(places) + ["STAY"]}
        required.append("where")
    return {"type": "object", "required": required, "properties": props}


def hero_decompose(hero, broad_step: str, n: int, span: str, cast: list, directive: str,
                   now: str, places: list) -> str:
    where = ""
    if places:
        where = (f' Also pick where {hero.name} should be for this whole step: one of the listed places, '
                 f'or "STAY" to remain at {hero.location}. Places: {"; ".join(places)}.')
    return (
        f"{cast_line(hero.name, cast)}\n{directive_block(directive)}\n"
        f"It is currently {now}. {hero.name}'s plan for this stretch: \"{broad_step}\"\n"
        f"Break it into {n} sequential actions, {span} each, one short line per action.{where}\n"
        'Reply as JSON: {"actions": ["...", ...]' + (', "where": "..."' if places else "") + "}"
    )


def hero_react(hero, other_name: str, other_doing: str, memories: list, cast: list,
               directive: str) -> str:
    memory_text = "\n".join(f"- {m}" for m in memories) or "(none yet)"
    return (
        f"{cast_line(hero.name, cast)}\n{directive_block(directive)}\n"
        f"Relevant memories:\n{memory_text}\n\n"
        f"{hero.name}'s current planned action: {hero.current_action}\n"
        f"New observation: {other_name} is nearby, currently: {other_doing}.\n\n"
        f"What does {hero.name} do? Reply with exactly one line, one of:\n"
        f"TALK: <what {hero.name} wants to talk to {other_name} about>\n"
        "REACT: <a different action, without talking>\n"
        "CONTINUE"
    )


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
    memory_text = "\n".join(f"- {m}" for m in memories) or "(nothing in particular)"
    so_far = "\n".join(transcript) or "(nobody has spoken yet)"
    opener = (f"{speaker.name} wants to talk about: {topic}\n" if topic and not transcript else "")
    return (
        f"{cast_line(speaker.name, cast)}\n{directive_block(directive) if speaker_is_hero else ''}\n"
        f"{speaker.name} and {listener_name} are face to face at {place}.\n"
        f"What {speaker.name} remembers about {listener_name} and related things:\n{memory_text}\n\n"
        f"{opener}Conversation so far:\n{so_far}\n\n"
        f"Write {speaker.name}'s next line: one or two sentences of spoken words only, no stage "
        f"directions, addressing only {listener_name}. "
        + (f"If the conversation has reached its natural end, reply with just {ccfg.END_MARKER}."
           if turn >= 2 else "")
        + (f" This is the last line (turn {turn + 1} of {max_turns})." if turn == max_turns - 1 else "")
    )


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
    return (
        "On a scale of 1 to 10, where 1 is purely mundane (e.g., brushing teeth, making a bed) "
        "and 10 is extremely poignant (e.g., a breakup, a college acceptance), rate the likely "
        f"poignancy of each of the following events or thoughts.\n\n{listing}\n\n"
        f'Reply as JSON: {{"ratings": [one integer 1-10 per item, {len(descriptions)} in all, in order]}}'
    )


FOCAL_SCHEMA = {"type": "object", "required": ["questions"],
                "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string"}}}}


def focal_points(hero, statements: list, n: int) -> str:
    listing = "\n".join(f"- {s}" for s in statements)
    return (
        f"Here are recent statements about {hero.name}:\n{listing}\n\n"
        f"Given only this information, what are the {n} most salient high-level questions we can "
        'ask about the subjects in these statements? Reply as JSON: {"questions": ["...", ...]}'
    )


INSIGHT_SCHEMA = {"type": "object", "required": ["insights"], "properties": {"insights": {
    "type": "array", "minItems": 1, "maxItems": 5, "items": {
        "type": "object", "required": ["text", "because"],
        "properties": {"text": {"type": "string"}, "because": {"type": "array", "items": {"type": "integer"}}}}}}}


def insights(hero, focal: str, statements: list, n: int) -> str:
    listing = "\n".join(f"{i}. {s}" for i, s in enumerate(statements))
    return (
        f"Statements about {hero.name}:\n{listing}\n\n"
        f"What {n} high-level insights can you infer from the above statements, in relation to: "
        f'"{focal}"? For each, list the statement numbers it is based on. Reply as JSON: '
        '{"insights": [{"text": "...", "because": [1, 3]}, ...]}'
    )


# --- Calls: background -----------------------------------------------------------------------

def schedule_schema(places: list) -> dict:
    return {"type": "object", "required": ["schedule"], "properties": {"schedule": {
        "type": "array", "minItems": 3, "maxItems": 8, "items": {
            "type": "object", "required": ["start", "end", "activity", "place"],
            "properties": {"start": {"type": "string"}, "end": {"type": "string"},
                           "activity": {"type": "string"},
                           "place": {"type": "string", "enum": list(places)}}}}}}


def background_schedule(b, places: list, day_label: str, directive: str) -> str:
    return (
        f"{directive_block(directive)}\n"
        f"Write {b.name}'s schedule for {day_label}, midnight to midnight: 3 to 8 blocks in order, "
        "each with a 24-hour start and end time (\"HH:MM\"), a short activity, and a place from "
        f"this list only: {'; '.join(places)}. \"home\" is their own home; \"elsewhere\" is "
        "anywhere else in the city. They work at "
        f"{b.work or 'no fixed place'} and like to spend free time at {b.haunt or 'home'}.\n"
        'Reply as JSON: {"schedule": [{"start": "07:00", "end": "08:00", "activity": "...", "place": "..."}, ...]}'
    )


def bio_upgrade(b, place: str) -> str:
    return (
        f"{b.name} is a {b.age}-year-old {b.occupation} in this city in {YEAR}. What little is "
        f"known: {b.bio}\nTheir usual haunts: {b.work or 'no fixed workplace'}, {b.haunt or 'home'}. "
        f"They are about to appear in a scene at {place}.\n"
        "Write a 4-5 sentence character dossier, third person, consistent with the facts above: "
        "who they are, what they want, one secret or pressure in their life, and a concrete "
        "PHYSICAL DESCRIPTION and WARDROBE a costume designer could use. Then, on its own last "
        "line, 'QUIRK: <one distinctive habit, a few words>'."
    )


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
