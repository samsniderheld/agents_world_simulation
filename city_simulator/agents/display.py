"""Terminal color formatting for --verbose tracing of an agent's internal
thinking: plan generation and decomposition (planning.py), memory formation
with its LLM-rated importance (memory.py), perceive/react (agent.py), and
reflection's focal questions and insights (reflection.py). Plain ANSI escape
codes -- these agents run in an ordinary terminal, not a curses UI.
"""

import sys

_ENABLED = sys.stdout.isatty()

_RESET = "\033[0m" if _ENABLED else ""
_DIM = "\033[2m" if _ENABLED else ""

_AGENT_PALETTE = [
    "\033[96m",  # cyan
    "\033[92m",  # green
    "\033[93m",  # yellow
    "\033[95m",  # magenta
    "\033[94m",  # blue
    "\033[91m",  # red
] if _ENABLED else [""]

_PLAN_TAG = "\033[1;94m" if _ENABLED else ""      # bold blue
_DECOMPOSE_TAG = "\033[34m" if _ENABLED else ""   # blue
_OBSERVE_TAG = "\033[36m" if _ENABLED else ""     # cyan
_REACT_TAG = "\033[1;95m" if _ENABLED else ""     # bold magenta
_CONTINUE_TAG = "\033[2m" if _ENABLED else ""     # dim
_MEMORY_TAG = "\033[2m" if _ENABLED else ""       # dim
_FOCAL_TAG = "\033[93m" if _ENABLED else ""       # yellow
_INSIGHT_TAG = "\033[1;93m" if _ENABLED else ""   # bold yellow


def agent_colors(names: list) -> dict:
    """Assign each agent name a stable color from the palette, in the
    order they're first seen, so the same agent reads in the same color
    for the whole run."""
    return {name: _AGENT_PALETTE[i % len(_AGENT_PALETTE)] for i, name in enumerate(names)}


# Hex equivalents of _AGENT_PALETTE, same order, so an agent's color in the
# terminal matches its color in viewer.html (see recorder.py).
_AGENT_HEX_PALETTE = [
    "#22d3ee",  # cyan
    "#4ade80",  # green
    "#fbbf24",  # yellow
    "#e879f9",  # magenta
    "#60a5fa",  # blue
    "#f87171",  # red
]


def agent_hex_colors(names: list) -> dict:
    """Hex equivalents of agent_colors(), for recorder.py's run log."""
    return {name: _AGENT_HEX_PALETTE[i % len(_AGENT_HEX_PALETTE)] for i, name in enumerate(names)}


def _tag(label: str, color: str) -> str:
    return f"{color}{label:<9}{_RESET}"


def _name(agent_name: str, color: str) -> str:
    return f"{color}{agent_name}{_RESET}"


def _clean(text: str, limit: int = 160) -> str:
    """Collapse a memory description (which may be multi-line, e.g. a full
    chat transcript) to one readable line for a trace."""
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def plan_line(agent_name: str, color: str, plan_items: list) -> str:
    """A fresh daily plan was generated -- planning.generate_daily_plan."""
    items = _clean("; ".join(plan_items))
    return f"    {_tag('PLAN', _PLAN_TAG)} {_name(agent_name, color)}'s plan for today: {items}"


def decompose_line(agent_name: str, color: str, broad_step: str, substeps: list) -> str:
    """A broad plan step was broken into finer actions -- planning.decompose."""
    items = _clean("; ".join(substeps))
    step = _clean(broad_step, 60)
    return f"    {_tag('DECOMPOSE', _DECOMPOSE_TAG)} {_name(agent_name, color)} breaks \"{step}\" into: {items}"


def observation_line(agent_name: str, color: str, observation: str) -> str:
    """`agent_name` notices something -- printed right before react() runs."""
    return f"    {_tag('OBSERVES', _OBSERVE_TAG)} {_name(agent_name, color)} notices: {_clean(observation)}"


def reaction_line(agent_name: str, color: str, new_action: str) -> str:
    """`agent_name` broke from its plan -- react() returned True."""
    return f"    {_tag('REACTS', _REACT_TAG)} {_name(agent_name, color)} reacts: {_clean(new_action)}"


def continue_line(agent_name: str, color: str) -> str:
    """`agent_name` stuck with its plan -- react() returned False."""
    line = f"    {_tag('CONTINUES', _CONTINUE_TAG)} {_name(agent_name, color)} sticks with the plan"
    return f"{_DIM}{line}{_RESET}" if _ENABLED else line


def memory_line(agent_name: str, color: str, kind: str, importance: float, description: str) -> str:
    """A new MemoryNode was formed -- MemoryStream.add, after the LLM rates
    its poignancy 1-10."""
    line = (
        f"    {_tag('MEMORY', _MEMORY_TAG)} {_name(agent_name, color)} remembers "
        f"({kind}, importance {importance:.0f}/10): {_clean(description)}"
    )
    return f"{_DIM}{line}{_RESET}" if _ENABLED else line


def focal_line(agent_name: str, color: str, question: str) -> str:
    """A reflection focal point (high-level question) was generated."""
    return f"    {_tag('FOCAL', _FOCAL_TAG)} {_name(agent_name, color)} wonders: {_clean(question)}"


def insight_line(agent_name: str, color: str, insight: str) -> str:
    """A reflection insight was distilled from retrieved memories."""
    return f"    {_tag('INSIGHT', _INSIGHT_TAG)} {_name(agent_name, color)} realizes: {_clean(insight)}"
