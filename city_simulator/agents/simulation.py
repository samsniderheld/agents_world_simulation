"""The runnable simulation, decoupled from any particular interface.

server.py's /api/run calls run() on a background thread; everything it
does is streamed live through recorder.py rather than returned, since the
frontend is watching the event log, not this function's return value.
"""

from . import config
from . import display
from . import llm
from .agent import Agent
from .treatment import generate_treatment
from .world import World
from . import recorder

AGENT_ROSTER = {
    "Oswald": dict(
        age=58,
        traits="seasoned bartender, patient, likeable, quiet, a good listener.",
        currently="cleaning glasses in the bar, getting ready for the evening",
        location="Ozzy's Bar",
    ),
    "Lou": dict(
        age=45,
        traits="down on his luck private eye detective, cynical, lonely, alcoholic",
        currently="nursing a hangover at Ozzy's Bar",
        location="Ozzy's Bar",
    ),
    "Veronica": dict(
        age=32,
        traits="sultry lounge singer, sharp-tongued, guarded, more dangerous than she lets on",
        currently="rehearsing her set for tonight's show at Ozzy's Bar",
        location="Ozzy's Bar",
    ),
    "Marsh": dict(
        age=50,
        traits="corrupt police detective, gruff, always working an angle, hides menace behind a friendly voice",
        currently="stopping by Ozzy's Bar to collect a favor",
        location="Ozzy's Bar",
    ),
    "Sal": dict(
        age=61,
        traits="aging mob boss, calm and courteous on the surface, ruthless underneath, expects respect",
        currently="holding court in his usual booth at Ozzy's Bar",
        location="Ozzy's Bar",
    ),
}


_HUB_COUNT = 3  # a small, fixed number of shared "scenes" agents can occupy

# Set by server.py once a history has finished generating (see
# set_history_roster below); while it's None, the hardcoded noir cast above
# is what roster_summary()/build_agents() draw from.
_active_roster = None


def _pick_hubs(history: dict) -> list:
    """A history's own richest still-active places, standing in for "wherever
    everyone in town still actually gathers" -- world.py has no movement, so
    a handful of shared location strings is the only way two agents can ever
    end up co-located (and therefore able to talk)."""
    active = [p for p in history.get("places", []) if p.get("status") == "active"]
    pool = active or history.get("places", [])
    pool = sorted(pool, key=lambda p: len(p.get("history", [])), reverse=True)
    return [p["name"] for p in pool[:_HUB_COUNT]] or ["the city"]


def roster_from_history(history: dict) -> dict:
    """A history's generated characters, restaged as an agent roster:
    each keeps their real grounded bio, but is assigned round-robin across
    a few shared hub locations (see _pick_hubs) instead of their own
    individual, almost-certainly-unique grounding place."""
    hubs = _pick_hubs(history)
    roster = {}
    for i, c in enumerate(history.get("characters", [])):
        traits = (c.get("occupation") or "").strip()
        quirk = (c.get("quirk") or "").strip()
        if quirk:
            traits = f"{traits}; {quirk}" if traits else quirk
        roster[c["name"]] = dict(
            age=c.get("age", 40),
            traits=traits or "a longtime local",
            currently=c.get("bio", ""),
            location=hubs[i % len(hubs)],
        )
    return roster


def set_history_roster(history: dict = None):
    """Point the agent roster at a generated history's characters (or, if
    called with None, back at the hardcoded noir cast)."""
    global _active_roster
    _active_roster = roster_from_history(history) if history else None


def _current_roster() -> dict:
    return _active_roster or AGENT_ROSTER


def roster_summary() -> list:
    """The available cast, for the frontend's agent picker."""
    return [{"name": name, **attrs} for name, attrs in _current_roster().items()]


def build_agents(names: list) -> list:
    roster = _current_roster()
    chosen = [n for n in names if n in roster] or [next(iter(roster))]
    return [Agent(name=name, **roster[name]) for name in chosen]


def run(ticks: int = 8, chat_model: str = None, embed_model: str = None,
        context_tokens: int = None, tick_sleep: float = 0,
        agent_names: list = None, verbose: bool = False, stop_flag=None):
    """Blocking -- meant to be called on a background thread (see
    server.py). Configures config.py's overridable settings, builds the
    chosen agents, and runs the tick loop."""
    if chat_model:
        config.CHAT_MODEL = chat_model
    if embed_model:
        config.EMBED_MODEL = embed_model
    if context_tokens:
        config.CHAT_CONTEXT_TOKENS = context_tokens

    llm.check_connection()

    agents = build_agents(agent_names or list(_current_roster()))
    agent_hex_colors = display.agent_hex_colors([a.name for a in agents])

    recorder.start(
        agents=[
            {
                "name": a.name, "color": agent_hex_colors[a.name],
                "age": a.age, "traits": a.traits, "location": a.location,
            }
            for a in agents
        ],
        meta={
            "chat_model": config.CHAT_MODEL, "embed_model": config.EMBED_MODEL,
            "context_tokens": config.CHAT_CONTEXT_TOKENS, "ticks": ticks,
        },
    )

    world = World(agents, tick_sleep=tick_sleep, verbose=verbose, stop_flag=stop_flag)
    world.run(ticks)

    treatment = generate_treatment(world.log, [a.name for a in agents])
    recorder.log("treatment", world.tick, text=treatment)
    recorder.save("run_log.json")
