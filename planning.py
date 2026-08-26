"""Planning: a rough daily plan in broad strokes, decomposed one level into
finer-grained steps. (The paper recursively decomposes down to 5-15 minute
chunks; this barebones version stops after one level of decomposition, which
is enough for a short simulated run -- see README for how to extend it.)
"""

import llm
from agent import Agent
from textutil import cast_constraint, parse_list_lines


def generate_daily_plan(agent: Agent, tick: int, known_names: list = None) -> list[str]:
    """Ask the LLM for a 5-8 item broad-strokes schedule for today, store it
    as a 'plan' memory, and set it as the agent's active plan."""
    prompt = (
        f"{agent.identity_summary()}\n\n"
        f"{cast_constraint(agent.name, known_names)}\n\n"
        f"In broad strokes, write {agent.name}'s schedule for today, starting "
        f"at {agent.wake_up_hour}:00 am. Give 5 to 8 items, each a short "
        "phrase like 'eat breakfast' or 'work on the mural at the studio', "
        "in the order they'll happen. One item per line, no numbering, no times."
    )
    reply = llm.complete(prompt, temperature=0.7)
    plan = parse_list_lines(reply)

    agent.plan = plan
    agent.plan_cursor = 0
    agent.memory.add(
        f"{agent.name}'s plan for today: {'; '.join(plan)}",
        kind="plan",
        tick=tick,
    )
    return plan


def decompose(agent: Agent, broad_step: str, tick: int, n_substeps: int = 3,
              known_names: list = None) -> list[str]:
    """Break one broad-strokes plan item into a handful of finer actions."""
    prompt = (
        f"{agent.identity_summary()}\n\n"
        f"{cast_constraint(agent.name, known_names)}\n\n"
        f"{agent.name}'s broad plan step: \"{broad_step}\"\n\n"
        f"Break this into {n_substeps} smaller, sequential actions "
        f"(a few minutes each). One action per line, no numbering."
    )
    reply = llm.complete(prompt, temperature=0.7)
    substeps = parse_list_lines(reply)[:n_substeps] or [broad_step]

    agent.memory.add(
        f"{agent.name} broke '{broad_step}' into: {'; '.join(substeps)}",
        kind="plan",
        tick=tick,
    )
    return substeps


def next_action(agent: Agent, tick: int, known_names: list = None) -> str:
    """Pop the next broad step off today's plan and use it as the current
    action, decomposing it first for a bit of texture. `known_names` should
    be the names of every other agent in the simulation, so planning never
    invents a new named character."""
    if agent.plan_cursor >= len(agent.plan):
        generate_daily_plan(agent, tick, known_names=known_names)

    if not agent.plan:
        agent.current_action = "idle"
        return agent.current_action

    broad_step = agent.plan[agent.plan_cursor]
    agent.plan_cursor += 1
    substeps = decompose(agent, broad_step, tick, known_names=known_names)
    agent.current_action = substeps[0]
    return agent.current_action
