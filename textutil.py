"""Parsing helpers for turning an LLM's free-text list reply into clean items."""

import re

_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_PREAMBLE_STARTS = (
    "here are", "here's", "sure", "okay", "ok", "certainly", "the following",
)


def first_spoken_line(text: str) -> str:
    """Given a chat completion that's supposed to be a single line of
    dialogue, drop any trailing meta-commentary paragraph a model tacks on
    (e.g. 'This line feels like a natural continuation...') and return just
    the spoken line.
    """
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if para.startswith("(") and para.endswith(")"):
            continue
        if para.lower().startswith(("this line", "note:", "this feels", "this response")):
            continue
        return para
    return text.strip()


def cast_constraint(agent_name: str, known_names: list) -> str:
    """A prompt line telling the LLM exactly who else exists in the
    simulation, so it doesn't invent a new named character (e.g. a
    bartender called 'Vinnie') that then contaminates memory retrieval and
    later dialogue -- see README for this failure mode. Used anywhere an
    agent generates free-text action or reaction descriptions.
    """
    others = [n for n in (known_names or []) if n != agent_name]
    if others:
        return (
            f"The only other named people who exist in this simulation are: "
            f"{', '.join(others)}. Do not invent or name any other person. "
            "Refer to anyone else only in generic, unnamed terms "
            "(e.g. 'the bartender', 'a passerby')."
        )
    return (
        "No other named people exist in this simulation yet. Do not invent "
        "or name anyone -- refer to anyone else only in generic, unnamed "
        "terms (e.g. 'the bartender', 'a passerby')."
    )


def parse_list_lines(text: str) -> list[str]:
    """Strip bullet/numbering markers from each line and drop obvious
    preamble lines like 'Here are the 3 actions:' that models sometimes
    prepend before the actual list.
    """
    items = []
    for raw in text.splitlines():
        line = _LIST_MARKER.sub("", raw.strip()).strip()
        if not line:
            continue
        lowered = line.lower()
        looks_like_preamble = line.endswith(":") and (
            len(line.split()) <= 8 or lowered.startswith(_PREAMBLE_STARTS)
        )
        if looks_like_preamble:
            continue
        items.append(line)
    return items
