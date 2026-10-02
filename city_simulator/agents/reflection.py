"""Reflection: periodically synthesize higher-level thoughts from recent
memories, mirroring reflect.py in the reference implementation.

Trigger: fires once the sum of importance scores of new observations since
the last reflection crosses REFLECTION_IMPORTANCE_THRESHOLD. When it fires:
  1. Ask the LLM for a few salient high-level questions ("focal points")
     given the agent's recent memories.
  2. For each focal point, retrieve relevant memories and ask the LLM to
     distill insights, citing which retrieved memories support each one.
  3. Store each insight as a new "reflection" memory node, with `evidence`
     pointing back at the memory ids it was drawn from.
"""

import re

import theme

from . import display
from . import llm
from . import recorder
from .agent import Agent
from .textutil import parse_list_lines
from .config import (
    REFLECTION_IMPORTANCE_THRESHOLD,
    REFLECTION_LOOKBACK,
    REFLECTION_NUM_FOCAL_POINTS,
    REFLECTION_INSIGHTS_PER_FOCAL_POINT,
)


def should_reflect(agent: Agent) -> bool:
    return agent.memory.importance_since_reflection >= REFLECTION_IMPORTANCE_THRESHOLD


def _generate_focal_points(agent: Agent, tick: int, verbose: bool = False, color: str = "") -> list[str]:
    recent = agent.memory.recent(REFLECTION_LOOKBACK, kinds=("observation",))
    statements = "\n".join(f"- {m.description}" for m in recent)
    prompt = theme.current().prompt("scene.focal_points", name=agent.name, statements=statements,
                                    n=REFLECTION_NUM_FOCAL_POINTS)
    reply = llm.complete(prompt, temperature=0.6)
    questions = parse_list_lines(reply)
    focal_points = questions[:REFLECTION_NUM_FOCAL_POINTS] or [theme.current().prompt("scene.focal_fallback", name=agent.name)]
    for question in focal_points:
        if verbose:
            print(display.focal_line(agent.name, color, question))
        recorder.log("focal", tick, agent=agent.name, text=question)
    return focal_points


def _generate_insights(agent: Agent, focal_point: str, tick: int,
                        verbose: bool = False, color: str = ""):
    nodes = agent.memory.retrieve(focal_point, tick, k=10)
    if not nodes:
        return
    statements = "\n".join(f"{i}. {n.description}" for i, n in enumerate(nodes))

    prompt = theme.current().prompt("scene.insights", name=agent.name, statements=statements,
                                    n=REFLECTION_INSIGHTS_PER_FOCAL_POINT, focal=focal_point)
    reply = llm.complete(prompt, temperature=0.6)

    for line in parse_list_lines(reply):
        match = re.match(r"(.*)\(because of ([\d,\s]+)\)\s*$", line)
        if match:
            insight = match.group(1).strip()
            indices = [int(x) for x in re.findall(r"\d+", match.group(2))]
        else:
            insight = line
            indices = []
        evidence_ids = [nodes[i].id for i in indices if 0 <= i < len(nodes)]
        if insight:
            if verbose:
                print(display.insight_line(agent.name, color, insight))
            recorder.log("insight", tick, agent=agent.name, text=insight, evidence=evidence_ids)
            agent.memory.add(insight, kind="reflection", tick=tick, evidence=evidence_ids,
                              agent_name=agent.name, color=color, verbose=verbose)


def reflect(agent: Agent, tick: int, verbose: bool = False, color: str = ""):
    """Run a full reflection pass if the importance threshold has been hit."""
    if not should_reflect(agent):
        return False

    focal_points = _generate_focal_points(agent, tick, verbose=verbose, color=color)
    for focal_point in focal_points:
        _generate_insights(agent, focal_point, tick, verbose=verbose, color=color)

    agent.memory.importance_since_reflection = 0.0
    return True
