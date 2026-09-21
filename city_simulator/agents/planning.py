"""Planning: a rough daily plan in broad strokes, decomposed one level into
finer-grained steps. (The paper recursively decomposes down to 5-15 minute
chunks; this barebones version stops after one level of decomposition, which
is enough for a short simulated run -- see README for how to extend it.)
"""

from . import display
from . import llm
from . import recorder
from .agent import Agent
from .textutil import cast_constraint, directive_block, extract_tagged_line, parse_list_lines


def generate_daily_plan(agent: Agent, tick: int, known_names: list = None,
                         verbose: bool = False, color: str = "", directive: str = None) -> list[str]:
    """Ask the LLM for a 5-8 item broad-strokes schedule for today, store it
    as a 'plan' memory, and set it as the agent's active plan.

    Retrieves from memory before asking -- for an agent hydrated from past
    runs (see simulation.py's _hydrate_agents), this is what actually lets
    "today" build on what already happened instead of replaying the same
    day every run; for a brand-new agent it's just "(no memories yet)".
    `directive` is the Simulation node's free-text scene guidance, if any
    (see textutil.directive_block) -- shaping the whole day's plan is the
    broadest lever it has, before decompose()/react() get a narrower say."""
    memories = agent.memory.retrieve(
        f"{agent.name}'s past days, plans, and what actually happened", tick, k=8,
    )
    memory_text = "\n".join(f"- {m.description}" for m in memories) or "(no memories yet)"

    prompt = (
        f"{agent.identity_summary()}\n\n"
        f"{cast_constraint(agent.name, known_names)}\n"
        f"{directive_block(directive)}\n"
        f"What {agent.name} remembers from before (may span several earlier days) -- for "
        f"context only, NOT a template to repeat:\n{memory_text}\n\n"
        f"It is a new day for {agent.name}, who typically starts around: {agent.currently}. "
        "This is NOT the same day as any of the memories above -- do not reuse the same "
        "schedule or the same specific activities. Instead, move the story forward: pick up "
        "an unfinished thread, follow up on someone mentioned above, or react to a "
        "consequence of what already happened, but make today's actual tasks genuinely "
        "different from before. Give 5 to 8 items, each a short phrase like 'eat breakfast' "
        "or 'work on the mural at the studio', in the order they'll happen. One item per "
        "line, no numbering, no times."
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
              verbose: bool = False, color: str = "", directive: str = None) -> list[str]:
    """Break one broad-strokes plan item into a handful of finer actions,
    and -- once per broad step (every n_substeps ticks, not every tick) --
    also ask the LLM where the agent should be for that whole step,
    relocating them immediately if it's a real change. See world.py's
    docstring for why there's no travel time simulated. `directive` is the
    Simulation node's free-text scene guidance, if any (see
    textutil.directive_block)."""
    prompt = (
        f"{agent.identity_summary()}\n\n"
        f"{cast_constraint(agent.name, known_names)}\n"
        f"{directive_block(directive)}\n"
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
                 verbose: bool = False, color: str = "", directive: str = None) -> str:
    """Advance one step through the current broad step's decomposition,
    decomposing the next broad step off today's plan only once the current
    one's substeps are exhausted. `known_names` should be the names of
    every other agent in the simulation, so planning never invents a new
    named character. `known_places` is every place the agent could
    plausibly relocate to for the next broad step -- see decompose().
    `directive` is the Simulation node's free-text scene guidance, if any
    (see textutil.directive_block), passed straight through to both."""
    if agent.substep_cursor >= len(agent.substeps):
        if agent.plan_cursor >= len(agent.plan):
            generate_daily_plan(agent, tick, known_names=known_names, verbose=verbose, color=color,
                                 directive=directive)

        if not agent.plan:
            agent.current_action = "idle"
            return agent.current_action

        broad_step = agent.plan[agent.plan_cursor]
        agent.plan_cursor += 1
        agent.substeps = decompose(agent, broad_step, tick, known_names=known_names,
                                    known_places=known_places, verbose=verbose, color=color,
                                    directive=directive)
        agent.substep_cursor = 0

    agent.current_action = agent.substeps[agent.substep_cursor]
    agent.substep_cursor += 1
    return agent.current_action
