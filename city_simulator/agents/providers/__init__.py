"""get_provider() picks a Provider implementation by name -- config.PROVIDER
by default (set per-run by simulation.run(), see agents/routes.py's
POST /api/agents/run), or an explicit name for the one case that's never
provider-switched: agents/llm.py's embed() always asks for "ollama"
specifically, since embeddings have no Claude equivalent.

Memoized per provider name, not just once, so switching providers between
runs doesn't discard and recreate an instance still in use (matches
visuals/providers/__init__.py's same reasoning).
"""

from .. import config

AVAILABLE_PROVIDERS = ["ollama", "claude"]

_instances = {}


def get_provider(name: str = None):
    name = name or config.PROVIDER
    if name in _instances:
        return _instances[name]

    if name == "ollama":
        from .ollama import OllamaProvider
        instance = OllamaProvider()
    elif name == "claude":
        from .claude import ClaudeProvider
        instance = ClaudeProvider()
    else:
        raise ValueError(f"unknown agent LLM provider: {name!r}")

    _instances[name] = instance
    return instance
