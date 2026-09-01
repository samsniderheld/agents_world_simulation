"""The runnable simulation, decoupled from any particular interface.

server.py's /api/run calls run() on a background thread; everything it
does is streamed live through recorder.py rather than returned, since the
frontend is watching the event log, not this function's return value.
"""

import config
import display
import llm
from agent import Agent
from treatment import generate_treatment
from world import World
import recorder

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


def roster_summary() -> list:
    """The available cast, for the frontend's agent picker."""
    return [{"name": name, **attrs} for name, attrs in AGENT_ROSTER.items()]


def build_agents(names: list) -> list:
    chosen = [n for n in names if n in AGENT_ROSTER] or ["Lou"]
    return [Agent(name=name, **AGENT_ROSTER[name]) for name in chosen]


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

    agents = build_agents(agent_names or list(AGENT_ROSTER))
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
