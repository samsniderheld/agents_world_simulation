"""Turns a finished run's transcript into a short video-vignette
treatment. This is deliberately not an Agent -- it has no memory stream or
ongoing state of its own, just a single LLM call. Triggered manually from a
Treatment node (agents/routes.py's POST /treatment) -- not automatically at
the end of every run.
"""

import datetime
import re

import theme

from . import config
from . import llm
from .config import TICK_MINUTES
from .world import clock_label

_STORYBOARD_HEADER_RE = re.compile(r"^\s*storyboard\s*:?\s*$", re.IGNORECASE)
_SHOT_LINE_RE = re.compile(r"^\s*\d+\.\s*(.+)$")

# World's default start (6:00 AM) -- runs saved before start_time was
# stored in their meta used it. Needed because a persisted "dialogue" event
# has no stored time field of its own (only "action" events do), so its
# display time is recomputed from its tick number the same way
# World.current_time showed it live.
_DEFAULT_START_TIME = datetime.datetime(2026, 8, 24, 6, 0)


def build_transcript(agent_records: dict, started_at: str) -> tuple:
    """Reconstructs one run's full narrative transcript from persisted
    per-agent records -- needed because citystate.store.append_agent_run()
    splits a run's events per agent, so any one agent's own file only ever
    holds their half of a conversation. `agent_records` is {name: full
    citystate.store.get_agent() record} for every character in the active
    city -- fetching those is the caller's job (agents/routes.py), so this
    module stays a pure transcript/text transform with no citystate
    dependency of its own. Collects every run (from any record) whose
    started_at matches and merges their events back into one list -- the
    participants of that run are exactly whoever has a matching run.

    Returns (log, agent_names, locations): `log` is a list of stamped
    narrative lines in the same shape World.log would have held live (only
    "action" and "dialogue" events ever became a line there); `agent_names`
    is every agent who actually appears, for generate_treatment()'s "don't
    invent anyone else" instruction. `locations` is every place an action
    event was tagged with, in first-seen order -- action lines already
    carry their location inline ("Pearl (Fothergill's Wharfside Tavern):
    ..."), but that's one detail buried per-line among many, easy for the
    model to treat as flavor text rather than the actual setting; pulling
    it out separately lets generate_treatment() state it up front as a
    fact about the scene instead. Dialogue events carry no location field
    at all (recorder.py's schema), so a transcript that's pure
    conversation with no action lines yields an empty list here -- callers
    must handle that, not assume there's always at least one.
    """
    merged_events = []
    agent_names = set()
    tick_minutes = TICK_MINUTES  # runs from before this was stored used the default
    start = _DEFAULT_START_TIME
    for name, record in agent_records.items():
        for run in (record or {}).get("runs", []):
            if run.get("started_at") != started_at:
                continue
            merged_events.extend(run.get("events", []))
            meta = run.get("meta") or {}
            tick_minutes = meta.get("tick_minutes") or tick_minutes
            if meta.get("start_time"):
                hour, minute = (int(x) for x in meta["start_time"].split(":"))
                start = _DEFAULT_START_TIME.replace(hour=hour, minute=minute)
            agent_names.add(name)

    narrative = [e for e in merged_events if e.get("kind") in ("action", "dialogue")]
    narrative.sort(key=lambda e: (e.get("tick", 0), 0 if e["kind"] == "action" else 1))

    log = []
    locations = []
    for e in narrative:
        if e["kind"] == "action":
            time = e.get("time", "")
            location = e.get("location")
            log.append(f"[{time}] {e.get('agent')} ({location}): {e.get('text')}")
            if location and location not in locations:
                locations.append(location)
        else:
            when = start + datetime.timedelta(minutes=tick_minutes * e.get("tick", 0))
            time = clock_label(start, when, tick_minutes)
            log.append(f"[{time}] {e.get('agent')}: {e.get('text')}")

    return log, sorted(agent_names), locations


def build_city_transcript(agent_records: dict, started_at: str, place: str = None,
                          tick_from: int = None, tick_to: int = None, max_lines: int = 300) -> tuple:
    """build_transcript() for a CITY run (meta.mode "city"): the same
    (log, agent_names, locations) result, built from the heroes' saved
    slices -- their actions and dialogue, plus the lines background
    residents spoke to them -- optionally narrowed to one place and/or a
    window of ticks, and capped at `max_lines`, so a run of hundreds of
    agents still makes a bounded prompt. Only people who actually appear in
    the narrowed transcript are named in `agent_names`."""
    events, seen = [], set()
    for record in agent_records.values():
        for run in (record or {}).get("runs", []):
            if run.get("started_at") != started_at:
                continue
            for e in run.get("events", []):
                key = e.get("seq") or (e.get("kind"), e.get("agent"), e.get("tick"), e.get("text"))
                if key not in seen:
                    seen.add(key)
                    events.append(e)

    def keep(e):
        if e.get("kind") not in ("action", "dialogue"):
            return False
        if tick_from is not None and e.get("tick", 0) < tick_from:
            return False
        if tick_to is not None and e.get("tick", 0) > tick_to:
            return False
        where = e.get("location") if e["kind"] == "action" else e.get("place")
        return place is None or where == place

    narrative = sorted((e for e in events if keep(e)),
                       key=lambda e: (e.get("tick", 0), 0 if e["kind"] == "action" else 1, e.get("seq") or 0))
    narrative = narrative[:max_lines]
    log, names, locations = [], [], []
    for e in narrative:
        where = e.get("location") if e["kind"] == "action" else e.get("place")
        if e["kind"] == "action":
            log.append(f"[{e.get('time', '')}] {e.get('agent')} ({where}): {e.get('text')}")
        else:
            log.append(f"[{e.get('time', '')}] {e.get('agent')}: {e.get('text')}")
        for n in (e.get("agent"), e.get("listener")):
            if n and n not in names:
                names.append(n)
        if where and where not in locations:
            locations.append(where)
    return log, sorted(names), locations


def _setting_block(location_details: list) -> str:
    """Turns build_transcript()'s place names, once the caller (routes.py)
    has looked each one up against citystate for its real `architecture`
    text, into an explicit SETTING block. Without the real architecture,
    the model only ever sees a bare place *name* in each action line
    ("Pearl (Fothergill's Wharfside Tavern): ...") and has nothing to
    ground a visual description in -- so it invents one from the name
    alone (a "Wharfside Tavern" reliably became a wooden dockside pub in
    testing, when the actual place.architecture on file describes a
    gleaming chrome-and-glass restaurant facade). Falls back to just the
    name when a place has no architecture text on file, rather than
    silently dropping it from the setting block entirely."""
    if not location_details:
        return ""
    t = theme.current()
    names = ", ".join(loc["name"] for loc in location_details if loc.get("name"))
    lines = []
    for loc in location_details:
        name = loc.get("name")
        if not name:
            continue
        architecture = (loc.get("architecture") or "").strip()
        lines.append(t.prompt("treatment.setting_place", name=name, architecture=architecture) if architecture
                     else t.prompt("treatment.setting_place_unknown", name=name))
    body = "\n".join(lines)
    return t.prompt("treatment.setting", place_names=names, places=body) + "\n\n"


def _cast_block(cast_details: list) -> str:
    """Turns each participating character's real `bio` (which now includes
    a physical description and wardrobe -- see history/characters.py's
    _llm_character()/_fallback_character()) into an explicit CAST
    appearance block, the same idea as _setting_block above but for who's
    in the scene rather than where it's set. Without this, the model only
    ever sees bare names (the "Cast available" line below) and invents
    what everyone looks like from scratch, with nothing to keep repeat
    treatments of the same character consistent. Falls back to just the
    name when a character has no bio on file."""
    if not cast_details:
        return ""
    t = theme.current()
    lines = []
    for c in cast_details:
        name = c.get("name")
        if not name:
            continue
        bio = (c.get("bio") or "").strip()
        lines.append(t.prompt("treatment.cast_person", name=name, bio=bio) if bio
                     else t.prompt("treatment.cast_person_unknown", name=name))
    body = "\n".join(lines)
    return t.prompt("treatment.cast", people=body) + "\n\n"


def generate_treatment(log: list[str], agent_names: list[str], model: str = None,
                        provider: str = None, location_details: list = None,
                        cast_details: list = None, directive: str = None) -> str:
    """Ask the LLM to read a finished simulation's transcript and write a
    short video-vignette treatment: the characters involved, a description
    of what happens, and 6 storyboard image prompts, each with art
    direction, lighting direction, and DOP/camera direction. `provider`
    lets this one call use a different agent LLM provider than whatever
    the simulation itself ran on (see llm.py's chat()/complete()).
    `location_details` is [{"name": str, "architecture": str}, ...] --
    routes.py builds this from build_transcript()'s `locations` names
    matched against citystate's place records -- stated explicitly as a
    SETTING fact (real architecture included) rather than left for the
    model to notice only by reading each action line's inline "(location)"
    tag, which carries the name only. Without this, a convened scene
    (everyone deliberately placed together, see simulation.py's
    convene_at) still routinely drifted into storyboard shots set in each
    character's own separate, habitual haunt -- or, once the name alone
    was surfaced, into scenery invented from the name rather than the
    place's actual recorded appearance. `cast_details` is
    [{"name": str, "bio": str}, ...] -- see _cast_block above -- the same
    idea applied to who's in the scene. `directive` is the free-text scene
    direction the run itself was steered by (the Simulation node's text
    input, persisted in the run's meta), so the treatment is written
    toward the same intent."""
    t = theme.current()
    transcript = "\n".join(log) or t.template("treatment.empty_transcript")
    direction_line = (t.prompt("treatment.direction", directive=directive.strip()) + "\n\n"
                      if directive and directive.strip() else "")
    prompt = t.prompt("treatment.main", cast_names=", ".join(agent_names), cast_block=_cast_block(cast_details),
                      setting_block=_setting_block(location_details), direction_block=direction_line,
                      transcript=transcript, visual_look=t["world"]["visual_look"])
    return llm.complete(
        prompt, model=model, temperature=0.8,
        context_tokens=config.TREATMENT_CONTEXT_TOKENS, provider=provider,
    )


def parse_storyboard_shots(text: str) -> list:
    """Pulls the numbered shot lines out of a treatment's STORYBOARD
    section (agents/routes.py's GET /api/agents/treatment/shots, which the
    Treatment node calls) -- each returned line is the *whole* shot ("<shot
    description> | Art direction: ... | Lighting: ... | DOP: ..."), since
    that whole line is exactly what makes a good single-image prompt, not
    just the leading description. Returns however many shots were
    actually found (not hardcoded to 6 -- the LLM's own count can vary);
    an empty list if there's no STORYBOARD section at all, which callers
    must handle gracefully rather than assume a fixed count."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _STORYBOARD_HEADER_RE.match(line)), None)
    if start is None:
        return []

    shots = []
    for line in lines[start + 1:]:
        match = _SHOT_LINE_RE.match(line)
        if match:
            shots.append(match.group(1).strip())
    return shots
