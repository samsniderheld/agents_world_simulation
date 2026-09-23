"""The runnable simulation, decoupled from any particular interface.

agents/jobs.py calls run() on a background thread; everything it does is
streamed live through recorder.py rather than returned, since the
frontend is watching the event log, not this function's return value.
"""

from citystate import store as citystate

from . import config
from . import display
from . import llm
from .agent import Agent
from .memory import MemoryStream
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

# None until a history is generated (or one is hydrated from a saved city
# at startup -- see app.py) -- _current_roster() below falls back to
# AGENT_ROSTER until then.
_active_roster = None


def roster_from_history(history: dict) -> dict:
    """A history's generated characters, restaged as an agent roster: each
    keeps their real grounded bio AND starts out placed at their own real
    grounding place (character.place_name -- see history/characters.py),
    not some shared stand-in location. An agent can later relocate as
    their plan unfolds (see planning.decompose's WHERE line, and run()
    below for how the active city's places become their known
    destinations) -- but nothing an agent does ever contradicts where
    their bio says they started."""
    roster = {}
    for c in history.get("characters", []):
        traits = (c.get("occupation") or "").strip()
        quirk = (c.get("quirk") or "").strip()
        if quirk:
            traits = f"{traits}; {quirk}" if traits else quirk
        roster[c["name"]] = dict(
            age=c.get("age", 40),
            traits=traits or "a longtime local",
            currently=c.get("bio", ""),
            location=c.get("place_name") or "the city",
        )
    return roster


def set_history_roster(history: dict = None):
    """Point the agent roster at a generated history's characters (or, if
    called with None, back at the hardcoded noir cast)."""
    global _active_roster
    _active_roster = roster_from_history(history) if history else None


def _current_roster() -> dict:
    # Deliberately not `_active_roster or AGENT_ROSTER` -- a real history
    # with zero characters yet (e.g. just generated, before anyone's used
    # the manual "Generate Character" flow) sets _active_roster to {},
    # which is falsy and would otherwise silently fall back to the
    # hardcoded noir cast. Only "no history at all" (_active_roster is
    # None) should fall back to it.
    return AGENT_ROSTER if _active_roster is None else _active_roster


def roster_summary() -> list:
    """The available cast, for the frontend's agent picker."""
    return [{"name": name, **attrs} for name, attrs in _current_roster().items()]


def build_agents(names: list) -> list:
    roster = _current_roster()
    if not roster:
        return []
    chosen = [n for n in names if n in roster] or [next(iter(roster))]
    agents = [Agent(name=name, **roster[name]) for name in chosen]
    if _active_roster is not None:  # only a history-backed roster has citystate characters
        _hydrate_agents(agents)
    return agents


def _hydrate_agents(agents: list) -> None:
    """Reconstruct each agent's memory from every past run recorded
    against their citystate character, so a second (or Nth) run against
    the same generated cast remembers what happened before instead of
    starting blank. Only ever reached for the history roster -- the
    hardcoded AGENT_ROSTER has no matching citystate characters, and
    build_agents() never calls this for it, so that cast behaves exactly
    as it always has."""
    city = citystate.get()
    if not city:
        return
    name_to_id = {c["name"]: c["id"] for c in city.get("characters", [])}
    for agent in agents:
        agent_id = name_to_id.get(agent.name)
        if not agent_id:
            continue
        record = citystate.get_agent(agent_id)
        if record and record.get("runs"):
            agent.memory = MemoryStream.from_persisted(record)
            print(f"{agent.name} remembers {len(agent.memory.nodes)} things from earlier runs.")


def run(ticks: int = 8, provider: str = None, chat_model: str = None, embed_model: str = None,
        context_tokens: int = None, tick_sleep: float = 0,
        agent_names: list = None, verbose: bool = False, stop_flag=None, convene_at: str = None,
        directive: str = None):
    """Blocking -- meant to be called on a background thread (see
    agents/jobs.py). Configures config.py's overridable settings, builds
    the chosen agents, and runs the tick loop.

    `provider` picks which agent LLM backend generates chat completions
    ("ollama" or "claude" -- see agents/providers/); embeddings always use
    Ollama regardless (see llm.py's docstring). `chat_model` overrides
    whichever provider is active (CLAUDE_MODEL for "claude", CHAT_MODEL
    otherwise); `context_tokens` likewise overrides Ollama's input-context
    window or Claude's output max_tokens, whichever applies.

    `convene_at` (a place name, not id -- see routes.py's /run) overrides
    every selected agent's starting location for this run only, so they
    convene somewhere none of them are individually grounded. Setting
    a.location alone isn't enough to make them *stay* there, though --
    planning.decompose() independently asks each agent's own LLM call
    where it wants to be for its next broad step, with no awareness that
    this run is a convene; left alone, that call routinely relocates a
    convened agent back to their own bio-grounded haunt within the first
    couple of ticks, undoing the convene. World's anchored_agents (every
    convened agent's name) shuts that down by handing decompose() no
    place to relocate to at all, so they stay put for the whole run.
    world.py's co-presence check is plain `a.location == b.location`, and
    every event that carries a location already reads it live off the
    agent at log time (see recorder.py's docstring) -- the same mechanism
    that already lets an agent's bio-grounded starting location work with
    no special casing.

    `directive` is the Simulation node's own free-text field ("guide how
    the characters are interacting") -- passed straight through to World,
    which hands it to every plan/decompose/react/dialogue call this run
    makes (see textutil.directive_block for the actual prompt fragment)."""
    if provider:
        config.PROVIDER = provider
    if chat_model:
        if config.PROVIDER == "claude":
            config.CLAUDE_MODEL = chat_model
        else:
            config.CHAT_MODEL = chat_model
    if embed_model:
        config.EMBED_MODEL = embed_model
    if context_tokens:
        config.CHAT_CONTEXT_TOKENS = context_tokens
        config.CLAUDE_MAX_TOKENS = context_tokens

    llm.check_connection()

    agents = build_agents(agent_names or list(_current_roster()))
    if convene_at:
        for a in agents:
            a.location = convene_at
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
            "provider": config.PROVIDER,
            "chat_model": config.CLAUDE_MODEL if config.PROVIDER == "claude" else config.CHAT_MODEL,
            "embed_model": config.EMBED_MODEL,
            "context_tokens": config.CHAT_CONTEXT_TOKENS, "ticks": ticks,
            # Kept with the run so a later treatment of it knows what the
            # scene was steered toward (see agents/routes.py's /treatment).
            "directive": directive,
        },
    )

    city_data = citystate.get()
    if city_data and city_data.get("places"):
        known_places = sorted({
            p["name"] for p in city_data["places"]
            if p.get("status") == "active" and p.get("name")
        })
    else:
        known_places = sorted({a.location for a in agents})

    anchored_agents = {a.name for a in agents} if convene_at else None
    world = World(agents, tick_sleep=tick_sleep, verbose=verbose, stop_flag=stop_flag,
                  known_places=known_places, anchored_agents=anchored_agents, directive=directive)
    world.run(ticks)

    citystate.append_agent_run(recorder.to_dict())
