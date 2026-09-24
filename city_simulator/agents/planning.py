"""Planning: a rough daily plan in broad strokes, decomposed one level into
finer-grained steps. (The paper recursively decomposes down to 5-15 minute
chunks; this barebones version stops after one level of decomposition, which
is enough for a short simulated run -- see README for how to extend it.)
"""

from . import display
from . import llm
from . import recorder
from .agent import Agent
from .config import TICK_MINUTES
from .textutil import cast_constraint, directive_block, extract_tagged_line, parse_list_lines


def generate_plan(agent: Agent, tick: int, horizon_minutes: int, n_items: int,
                  known_names: list = None, verbose: bool = False, color: str = "",
                  directive: str = None, now: str = None, until: str = None) -> list[str]:
    """Ask the LLM what the agent is trying to do over the whole rest of the
    run -- `horizon_minutes` of simulated time, from `now` until `until` --
    as `n_items` broad items in order, each covering an equal share of it.
    A 4-hour run gets a 4-hour plan; a 7-day run gets a plan for the week
    (one goal per day), not a single day's errands repeated.

    Retrieves from memory before asking -- for an agent hydrated from past
    runs (see simulation.py's _hydrate_agents), this is what lets the new
    stretch build on what already happened instead of replaying it.
    `directive` is the Simulation node's free-text scene guidance, if any
    (see textutil.directive_block) -- shaping the whole plan is the
    broadest lever it has, before decompose()/react() get a narrower say."""
    memories = agent.memory.retrieve(
        f"{agent.name}'s past plans, goals, and what actually happened", tick, k=8,
    )
    memory_text = "\n".join(f"- {m.description}" for m in memories) or "(no memories yet)"
    horizon = _duration(horizon_minutes)
    window = f", from {now} until {until}" if now and until else ""

    prompt = (
        f"{agent.identity_summary()}\n\n"
        f"{cast_constraint(agent.name, known_names)}\n"
        f"{directive_block(directive)}\n"
        f"What {agent.name} remembers from before -- for context only, NOT a template "
        f"to repeat:\n{memory_text}\n\n"
        f"{agent.name} typically starts the day around: {agent.currently}.\n"
        f"Plan what {agent.name} is trying to do over the next {horizon}{window}: their "
        f"goals for that whole stretch and what they'll actually spend it on, sized to "
        f"the stretch -- a week's plan is a week of intentions, not one day's errands. "
        "This is NOT the same stretch as any of the memories above -- move the story "
        "forward: pick up an unfinished thread, follow up on someone mentioned above, or "
        "react to a consequence of what already happened.\n\n"
        f"Give exactly {n_items} items in the order they'll happen, each covering "
        f"roughly {_duration(horizon_minutes / n_items)}. Each item is a short phrase. "
        "One item per line, no numbering, no times."
    )
    reply = llm.complete(prompt, temperature=0.7)
    plan = parse_list_lines(reply)[:n_items]

    agent.plan = plan
    if verbose:
        print(display.plan_line(agent.name, color, plan))
    recorder.log("plan", tick, agent=agent.name, items=plan)
    agent.memory.add(
        f"{agent.name}'s plan for the next {horizon}: {'; '.join(plan)}",
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


# A plan never has more items than this -- a long run gets broader items,
# each spread across more ticks, rather than a sprawling list.
MAX_PLAN_ITEMS = 8


def _duration(minutes: float) -> str:
    """ "30 minutes", "4 hours", "7 days" -- for plan prompts."""
    minutes = round(minutes)
    if minutes >= 1440 and minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} day{'s' if days != 1 else ''}"
    if minutes >= 2880:
        return f"about {round(minutes / 1440)} days"
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if minutes >= 120:
        return f"about {round(minutes / 60)} hours"
    return f"{minutes} minutes"


def _now_line(now: str = None, extra: str = "") -> str:
    """The simulated time of day, for a planning prompt -- without it the
    model has no idea whether it's planning a morning or a midnight (a run
    can start at any hour; see simulation.run()'s start_time)."""
    if not now:
        return ""
    return f"It is currently {now}. {extra}".rstrip() + "\n\n"


def _substep_length(tick_minutes: int = None) -> str:
    """Each substep is exactly one tick, so the prompt should ask for
    actions that plausibly fill one -- "about 30 minutes", "about 2 hours"."""
    if not tick_minutes:
        return "a few minutes"
    if tick_minutes >= 1440:
        return "the whole day"
    if tick_minutes >= 60 and tick_minutes % 60 == 0:
        hours = tick_minutes // 60
        return f"about {hours} hour{'s' if hours != 1 else ''}"
    return f"about {tick_minutes} minutes"


def decompose(agent: Agent, broad_step: str, tick: int, n_substeps: int = 3,
              known_names: list = None, known_places: list = None,
              verbose: bool = False, color: str = "", directive: str = None,
              tick_minutes: int = None, now: str = None) -> list[str]:
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
        f"{_now_line(now)}"
        + (
            f"{agent.name}'s plan for this stretch: \"{broad_step}\"\n\n"
            f"Describe what {agent.name} actually does over this stretch "
            f"({_substep_length(tick_minutes)}) as ONE action -- a single short line, "
            "no numbering."
            if n_substeps == 1 else
            f"{agent.name}'s broad plan step: \"{broad_step}\"\n\n"
            f"Break this into {n_substeps} smaller, sequential actions "
            f"({_substep_length(tick_minutes)} each). One action per line, no numbering."
        )
        + f"{_where_prompt_block(agent, known_places)}"
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
                 verbose: bool = False, color: str = "", directive: str = None,
                 tick_minutes: int = None, now: str = None, total_ticks: int = None,
                 until: str = None) -> str:
    """This tick's action. On the agent's first turn, plans the whole rest
    of the run (see generate_plan) and spreads the plan's items evenly over
    the remaining ticks; each item is broken into exactly as many actions as
    it has ticks (one tick -> one action covering the whole tick). Items are
    pinned to ticks, so a tick spent in conversation doesn't push the rest
    of the plan later -- the agent resumes wherever the clock says.
    `known_names` should be every other agent's name, so planning never
    invents a new named character; `known_places` is every place the agent
    could relocate to -- see decompose(). `directive` is the Simulation
    node's free-text scene guidance, if any (see textutil.directive_block)."""
    span = tick_minutes or TICK_MINUTES
    total = max(1, total_ticks or 8)
    if not agent.plan:
        remaining = max(1, total - tick)
        n_items = min(remaining, MAX_PLAN_ITEMS)
        generate_plan(agent, tick, remaining * span, n_items, known_names=known_names,
                      verbose=verbose, color=color, directive=directive, now=now, until=until)
        if not agent.plan:
            agent.current_action = "idle"
            return agent.current_action
        n = len(agent.plan)
        agent.plan_bounds = [(tick + k * remaining // n, tick + (k + 1) * remaining // n) for k in range(n)]
        agent.current_item = -1

    item = next((k for k, (s, e) in enumerate(agent.plan_bounds) if s <= tick < e), len(agent.plan_bounds) - 1)
    start, end = agent.plan_bounds[item]
    if item != agent.current_item:
        agent.current_item = item
        agent.substeps = decompose(agent, agent.plan[item], tick, n_substeps=max(1, end - start),
                                   known_names=known_names, known_places=known_places,
                                   verbose=verbose, color=color, directive=directive,
                                   tick_minutes=tick_minutes, now=now)
    agent.current_action = agent.substeps[min(max(0, tick - start), len(agent.substeps) - 1)]
    return agent.current_action
