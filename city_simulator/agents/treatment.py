"""Turns a finished run's transcript into a short video-vignette
treatment. This is deliberately not an Agent -- it has no memory stream or
ongoing state of its own, just a single LLM call. Triggered manually, per
agent, from that agent's own modal (agents/routes.py's POST /treatment) --
not automatically at the end of every run.
"""

import datetime

from . import config
from . import llm
from .config import TICK_MINUTES

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

    Returns (log, agent_names): `log` is a list of stamped narrative
    lines in the same shape World.log would have held live (only "action"
    and "dialogue" events ever became a line there); `agent_names` is
    every agent who actually appears, for generate_treatment()'s "don't
    invent anyone else" instruction.
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
    for e in narrative:
        if e["kind"] == "action":
            time = e.get("time", "")
            log.append(f"[{time}] {e.get('agent')} ({e.get('location')}): {e.get('text')}")
        else:
            time = (_DEFAULT_START_TIME + datetime.timedelta(
                minutes=TICK_MINUTES * e.get("tick", 0))).strftime("%I:%M %p")
            log.append(f"[{time}] {e.get('agent')}: {e.get('text')}")

    return log, sorted(agent_names)


NOIR_LOOK = (
    "moody film noir aesthetic: high-contrast black-and-white lighting, hard "
    "venetian-blind shadows, wet city streets, dramatic low-key lighting, "
    "deep chiaroscuro shadow, 1940s wardrobe and production design."
    "the background should look like a painting, in the style of edward hopper."
)


def generate_treatment(log: list[str], agent_names: list[str], model: str = None,
                        provider: str = None) -> str:
    """Ask the LLM to read a finished simulation's transcript and write a
    short video-vignette treatment: the characters involved, a description
    of what happens, and 6 storyboard image prompts, each with art
    direction, lighting direction, and DOP/camera direction. `provider`
    lets this one call use a different agent LLM provider than whatever
    the simulation itself ran on (see llm.py's chat()/complete())."""
    transcript = "\n".join(log) or "(nothing happened)"

    prompt = (
        "You are a film treatment writer adapting a scene transcript into a "
        "short video vignette pitch, in a film noir style.\n\n"
        f"Cast available in this scene: {', '.join(agent_names)}. Only write "
        "about characters who actually appear in the transcript below; do "
        "not invent any other named characters.\n\n"
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
        "1. <shot description> | Art direction: <set/production design "
        "notes> | Lighting: <lighting setup> | DOP: <camera angle, lens, "
        "and movement>\n"
        "(exactly 6 numbered shots in this format, each a different beat of "
        f"the story, all consistent with a {NOIR_LOOK}.)"
        "the direction should take into account the japanese concept of MA, focusing on"
        "individual moments, the characters within them, and how those characters experience"
        "their environment"
    )
    return llm.complete(
        prompt, model=model, temperature=0.8,
        context_tokens=config.TREATMENT_CONTEXT_TOKENS, provider=provider,
    )
