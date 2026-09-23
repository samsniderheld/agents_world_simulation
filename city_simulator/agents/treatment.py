"""Turns a finished run's transcript into a short video-vignette
treatment. This is deliberately not an Agent -- it has no memory stream or
ongoing state of its own, just a single LLM call. Triggered manually from a
Treatment node (agents/routes.py's POST /treatment) -- not automatically at
the end of every run.
"""

import datetime
import re

from . import config
from . import llm
from .config import TICK_MINUTES

_STORYBOARD_HEADER_RE = re.compile(r"^\s*storyboard\s*:?\s*$", re.IGNORECASE)
_SHOT_LINE_RE = re.compile(r"^\s*\d+\.\s*(.+)$")

# Matches World.__init__'s own hardcoded default exactly (simulation.py's
# one World(...) call never overrides start_time) -- needed here because
# a persisted "dialogue" event has no stored time field of its own (only
# "action" events do), so its display time has to be recomputed from its
# tick number the same way World.current_time would have shown it live.
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
    for name, record in agent_records.items():
        for run in (record or {}).get("runs", []):
            if run.get("started_at") != started_at:
                continue
            merged_events.extend(run.get("events", []))
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
            time = (_DEFAULT_START_TIME + datetime.timedelta(
                minutes=TICK_MINUTES * e.get("tick", 0))).strftime("%I:%M %p")
            log.append(f"[{time}] {e.get('agent')}: {e.get('text')}")

    return log, sorted(agent_names), locations


NOIR_LOOK = (
    "moody film noir aesthetic: high-contrast black-and-white lighting, hard "
    "venetian-blind shadows, wet city streets, dramatic low-key lighting, "
    "deep chiaroscuro shadow, 1940s wardrobe and production design."
    "the background should look like a painting, in the style of edward hopper."
)


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
    names = ", ".join(loc["name"] for loc in location_details if loc.get("name"))
    lines = []
    for loc in location_details:
        name = loc.get("name")
        if not name:
            continue
        architecture = (loc.get("architecture") or "").strip()
        lines.append(f"- {name}: {architecture}" if architecture else f"- {name} (no recorded architecture)")
    body = "\n".join(lines)
    return (
        f"Setting: this entire scene takes place at {names}. Below is each place's "
        "REAL recorded appearance -- base every shot's art direction on this, not on "
        "what the name alone suggests, and do not invent or drift to any other "
        f"location:\n{body}\n\n"
    )


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
    lines = []
    for c in cast_details:
        name = c.get("name")
        if not name:
            continue
        bio = (c.get("bio") or "").strip()
        lines.append(f"- {name}: {bio}" if bio else f"- {name} (no recorded description)")
    body = "\n".join(lines)
    return (
        "Cast appearance reference -- use these real descriptions for how each character "
        "looks and what they wear, do not invent conflicting physical details:\n"
        f"{body}\n\n"
    )


def generate_treatment(log: list[str], agent_names: list[str], model: str = None,
                        provider: str = None, location_details: list = None,
                        cast_details: list = None) -> str:
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
    idea applied to who's in the scene."""
    transcript = "\n".join(log) or "(nothing happened)"
    setting_line = _setting_block(location_details)
    cast_line = _cast_block(cast_details)

    prompt = (
        "You are a film treatment writer adapting a scene transcript into a "
        "short video vignette pitch, in a film noir style.\n\n"
        f"Cast available in this scene: {', '.join(agent_names)}. Only write "
        "about characters who actually appear in the transcript below; do "
        "not invent any other named characters.\n\n"
        f"{cast_line}"
        f"{setting_line}"
        f"Transcript:\n{transcript}\n\n"
        "Write the treatment in exactly this format, with no extra "
        "commentary before or after it:\n\n"
        "CHARACTERS:\n"
        "- <name> -- <one-line description of their role in this vignette>\n"
        "(one line per character who actually appears)\n\n"
        "SYNOPSIS:\n"
        "<a tight paragraph, 4-8 sentences, describing what happens in this "
        "vignette, written as noir prose>\n\n"
        "STORYBOARD:\n"
        "1. <shot description> | Character: <physical description of "
        "whoever appears in this shot -- their build, face, and wardrobe, "
        "drawn from the cast appearance reference above, not invented -- "
        "or \"none\" for a shot with no one in frame> | Art direction: "
        "<set/production design notes> | Lighting: <lighting setup> | "
        "DOP: <camera angle, lens, and movement>\n"
        "(exactly 6 numbered shots in this format, each a different beat of "
        f"the story, all consistent with a {NOIR_LOOK}. Each shot line is used "
        "on its own, standalone, to generate that shot's actual image later -- "
        "the Character field must repeat enough of their real appearance that "
        "the shot still reads correctly by itself, without needing the rest "
        "of this treatment for context.)"
        "the direction should take into account the japanese concept of MA, focusing on"
        "individual moments, the characters within them, and how those characters experience"
        "their environment"
    )
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
