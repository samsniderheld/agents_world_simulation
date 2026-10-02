"""Dispatches to whichever agent LLM provider is active (config.PROVIDER
-- "ollama" by default, or "claude", set per-run by simulation.run()). See
providers/__init__.py's get_provider() for the swap point and
providers/base.py for the interface every provider implements.

Every other file in this package (agent.py, planning.py, memory.py,
reflection.py, treatment.py) imports this module and calls these same
functions regardless of provider -- none of them need to know a
provider swap is even possible. embed()/embed_many() are never
provider-switched: they always go to the ollama provider specifically,
since there's no Claude-API embeddings endpoint to swap them to.

Every call passes through a per-backend concurrency cap
(config.MAX_CONCURRENCY): the tick loop fires calls from many threads at
once, and this is what keeps that from swamping a local server or tripping
a hosted API's rate limit.
"""

import threading

from . import config
from . import providers

_caps: dict = {}
_caps_lock = threading.Lock()


def _cap(name: str) -> threading.Semaphore:
    with _caps_lock:
        if name not in _caps:
            limit = config.EMBED_MAX_CONCURRENCY if name == "embed" else config.MAX_CONCURRENCY.get(name, 4)
            _caps[name] = threading.BoundedSemaphore(limit)
        return _caps[name]


def chat(messages, model=None, temperature=0.7, context_tokens=None, provider=None) -> str:
    """`provider`, if given, overrides config.PROVIDER for just this one
    call (e.g. treatment.py letting a request pick a different provider
    than whatever the simulation itself is using) -- deliberately not a
    global config.PROVIDER mutation, since agent tick loops can be
    running concurrently in other threads against the same dispatcher."""
    name = provider or config.PROVIDER
    with _cap(name):
        return providers.get_provider(name).chat(
            messages, model=model, temperature=temperature, context_tokens=context_tokens,
        )


def complete(prompt: str, model=None, temperature=0.7, context_tokens=None, provider=None) -> str:
    """Convenience wrapper for a single user-turn prompt."""
    return chat([{"role": "user", "content": prompt}], model=model,
                temperature=temperature, context_tokens=context_tokens, provider=provider)


def embed(text: str, model=None) -> list:
    """Return an embedding vector for `text` -- always via Ollama, never
    the active chat provider (see module docstring)."""
    with _cap("embed"):
        return providers.get_provider("ollama").embed(text, model=model)


def embed_many(texts: list, model=None) -> list:
    """Embedding vectors for several texts in one request (always Ollama)."""
    if not texts:
        return []
    with _cap("embed"):
        return providers.get_provider("ollama").embed_many(texts, model=model)


def list_models() -> list:
    """Model names/ids for the active provider, for a UI picker."""
    return providers.get_provider().list_models()


def check_connection():
    """Raise a clear error early if the active chat provider -- and,
    whenever that provider isn't Ollama, the embedding model specifically
    -- aren't ready. Without the second check, a Claude-mode run would
    pass this and then crash confusingly on the first memory.add()."""
    providers.get_provider().check_connection()
    if config.PROVIDER != "ollama":
        providers.get_provider("ollama").check_embed_model()
