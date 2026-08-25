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
