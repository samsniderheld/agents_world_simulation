"""Planning: a rough daily plan in broad strokes, decomposed one level into
finer-grained steps. (The paper recursively decomposes down to 5-15 minute
chunks; this barebones version stops after one level of decomposition, which
is enough for a short simulated run -- see README for how to extend it.)
"""

from . import display
from . import llm
from . import recorder
from .agent import Agent
from .textutil import cast_constraint, extract_tagged_line, parse_list_lines


def generate_daily_plan(agent: Agent, tick: int, known_names: list = None,
                         verbose: bool = False, color: str = "") -> list[str]:
    """Ask the LLM for a 5-8 item broad-strokes schedule for today, store it
    as a 'plan' memory, and set it as the agent's active plan."""
    prompt = (
        f"{agent.identity_summary()}\n\n"
        f"{cast_constraint(agent.name, known_names)}\n\n"
        f"In broad strokes, write {agent.name}'s schedule for today, starting with "
        f"{agent.currently}. Give 5 to 8 items, each a short "
        "phrase like 'eat breakfast' or 'work on the mural at the studio', "
        "in the order they'll happen. One item per line, no numbering, no times."
    )
    reply = llm.complete(prompt, temperature=0.7)
    plan = parse_list_lines(reply)

    agent.plan = plan
    agent.plan_cursor = 0
    if verbose:
        print(display.plan_line(agent.name, color, plan))
    recorder.log("plan", tick, agent=agent.name, items=plan)
    agent.memory.add(
        f"{agent.name}'s plan for today: {'; '.join(plan)}",
        kind="plan",
        tick=tick,
        agent_name=agent.name, color=color, verbose=verbose,
    )
    return plan


def _where_prompt_block(agent: Agent, known_places: list = None) -> str:
    """Extra prompt text asking the LLM to also pick a destination for the
    whole upcoming broad step -- teleport-at-decompose-time only, no
    travel time or pathfinding (see world.py's docstring). Skipped
    entirely when there isn't a real choice to make (no known places, or
    only one), so a single-location cast never gets asked a vacuous
    question every decompose cycle."""
    places = [p for p in dict.fromkeys(known_places or []) if p]
    if len(places) < 2:
        return ""
    listing = "; ".join(places)
    return (
        f"\n\n{agent.name} is currently at \"{agent.location}\". Where should "
        f"{agent.name} be for this whole step? Pick exactly one place from "
        f"this list, or STAY to remain where {agent.name} is: {listing}\n"
        "On its own final line, after the actions above, write:\n"
        "WHERE: <one place name from the list, or STAY>"
    )


def _resolve_destination(where_raw, known_places: list, current_location: str):
    """Validate the LLM's WHERE reply against the real place list, failing
    closed (returning None, meaning "no move") on anything empty,
    unrecognized, STAY-like, or already-current -- an LLM reply must never
    be trusted to directly set agent.location."""
    if not where_raw or not known_places:
        return None
    normalized = where_raw.strip().strip('."\'')
    if not normalized or normalized.upper() in ("STAY", "SAME", "HERE", "N/A", "NONE", "CURRENT"):
        return None
    for place in known_places:
        if place.lower() == normalized.lower():
            return place if place != current_location else None
    for place in known_places:
        if place.lower() in normalized.lower() or normalized.lower() in place.lower():
            return place if place != current_location else None
    return None


def _move_agent(agent: Agent, destination: str, tick: int, verbose: bool = False, color: str = ""):
    """Actually relocate the agent -- only called once _resolve_destination
    has already validated `destination` against the known place list."""
    old_location = agent.location
    agent.location = destination
    recorder.update_agent_location(agent.name, destination)
    if verbose:
        print(display.move_line(agent.name, color, old_location, destination))
    recorder.log("move", tick, agent=agent.name, from_location=old_location, to_location=destination)
    agent.memory.add(
        f"{agent.name} moved from {old_location} to {destination}.",
        kind="observation",
        tick=tick,
        agent_name=agent.name, color=color, verbose=verbose,
    )


def decompose(agent: Agent, broad_step: str, tick: int, n_substeps: int = 3,
              known_names: list = None, known_places: list = None,
              verbose: bool = False, color: str = "") -> list[str]:
    """Break one broad-strokes plan item into a handful of finer actions,
    and -- once per broad step (every n_substeps ticks, not every tick) --
    also ask the LLM where the agent should be for that whole step,
    relocating them immediately if it's a real change. See world.py's
    docstring for why there's no travel time simulated."""
    prompt = (
        f"{agent.identity_summary()}\n\n"
        f"{cast_constraint(agent.name, known_names)}\n\n"
        f"{agent.name}'s broad plan step: \"{broad_step}\"\n\n"
        f"Break this into {n_substeps} smaller, sequential actions "
        f"(a few minutes each). One action per line, no numbering."
        f"{_where_prompt_block(agent, known_places)}"
    )
    reply = llm.complete(prompt, temperature=0.7)
    reply, where_raw = extract_tagged_line(reply, "WHERE")
    substeps = parse_list_lines(reply)[:n_substeps] or [broad_step]

    if verbose:
        print(display.decompose_line(agent.name, color, broad_step, substeps))
    recorder.log("decompose", tick, agent=agent.name, broad_step=broad_step, items=substeps)
    agent.memory.add(
        f"{agent.name} broke '{broad_step}' into: {'; '.join(substeps)}",
        kind="plan",
        tick=tick,
        agent_name=agent.name, color=color, verbose=verbose,
    )

    destination = _resolve_destination(where_raw, known_places, agent.location)
    if destination:
        _move_agent(agent, destination, tick, verbose=verbose, color=color)

    return substeps


def next_action(agent: Agent, tick: int, known_names: list = None, known_places: list = None,
                 verbose: bool = False, color: str = "") -> str:
    """Advance one step through the current broad step's decomposition,
    decomposing the next broad step off today's plan only once the current
    one's substeps are exhausted. `known_names` should be the names of
    every other agent in the simulation, so planning never invents a new
    named character. `known_places` is every place the agent could
    plausibly relocate to for the next broad step -- see decompose()."""
    if agent.substep_cursor >= len(agent.substeps):
        if agent.plan_cursor >= len(agent.plan):
            generate_daily_plan(agent, tick, known_names=known_names, verbose=verbose, color=color)

        if not agent.plan:
            agent.current_action = "idle"
            return agent.current_action

        broad_step = agent.plan[agent.plan_cursor]
        agent.plan_cursor += 1
        agent.substeps = decompose(agent, broad_step, tick, known_names=known_names,
                                    known_places=known_places, verbose=verbose, color=color)
        agent.substep_cursor = 0

    agent.current_action = agent.substeps[agent.substep_cursor]
    agent.substep_cursor += 1
    return agent.current_action
