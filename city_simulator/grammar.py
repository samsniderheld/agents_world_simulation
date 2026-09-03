"""A small replacement grammar engine -- the actual mechanism the talk this
project is modeled on describes: a grammar is a set of named symbols, each
with one or more weighted expansion rules; expanding a symbol recursively
substitutes any {other_symbol} placeholders in the chosen rule, and fills
any {context_key} placeholders directly from a context dict supplied at
expansion time (a figure's name, a place's name, the current year, ...).

This -- not an LLM call -- is what generates the bulk of every Gospel: see
events.py for how event templates use it, including the causality
rationalization the talk describes (a {cause} symbol whose rules are
gated on entity state, e.g. "only pick this rule if the figure has a rival").
"""

import random
import re

_TOKEN_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _choose(rules: list, rng: random.Random):
    """`rules` is a list of either plain strings (equal weight) or
    (weight, string) tuples -- the two forms can be mixed freely."""
    weighted = [r if isinstance(r, tuple) else (1.0, r) for r in rules]
    total = sum(w for w, _ in weighted)
    roll = rng.uniform(0, total)
    upto = 0.0
    for weight, text in weighted:
        upto += weight
        if roll <= upto:
            return text
    return weighted[-1][1]  # floating-point safety net


def expand(grammar: dict, symbol: str, context: dict, rng: random.Random = None) -> str:
    """Expand a named symbol: pick one of its weighted rules, then expand
    that rule's text via expand_text()."""
    rng = rng or random
    if symbol not in grammar:
        raise KeyError(f"grammar has no rule for symbol {symbol!r}")
    template = _choose(grammar[symbol], rng)
    return expand_text(template, grammar, context, rng)


def expand_text(text: str, grammar: dict, context: dict, rng: random.Random = None) -> str:
    """Expand a raw template string (not necessarily a named symbol) using
    the same {symbol}/{context_key} substitution expand() uses. This is
    what event templates call with their top-level Gospel template."""
    rng = rng or random

    def _replace(match):
        name = match.group(1)
        if name in grammar:
            return expand(grammar, name, context, rng)
        if name in context:
            return str(context[name])
        raise KeyError(
            f"placeholder {{{name}}} is neither a grammar symbol nor a context "
            f"key (available context keys: {sorted(context)})"
        )

    return _TOKEN_RE.sub(_replace, text)
