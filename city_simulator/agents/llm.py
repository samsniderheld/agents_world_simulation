"""Dispatches to whichever agent LLM provider is active (config.PROVIDER
-- "ollama" by default, or "claude", set per-run by simulation.run()). See
providers/__init__.py's get_provider() for the swap point and
providers/base.py for the interface every provider implements.

Every other file in this package (agent.py, planning.py, memory.py,
reflection.py, treatment.py) imports this module and calls these same
five functions regardless of provider -- none of them need to know a
provider swap is even possible. embed() is the one function that's never
provider-switched: it always goes to the ollama provider specifically,
since there's no Claude-API embeddings endpoint to swap it to.
"""

from . import config
from . import providers


def chat(messages, model=None, temperature=0.7, context_tokens=None) -> str:
    return providers.get_provider().chat(
        messages, model=model, temperature=temperature, context_tokens=context_tokens,
    )


def complete(prompt: str, model=None, temperature=0.7, context_tokens=None) -> str:
    """Convenience wrapper for a single user-turn prompt."""
    return chat([{"role": "user", "content": prompt}], model=model,
                temperature=temperature, context_tokens=context_tokens)


def embed(text: str, model=None) -> list:
    """Return an embedding vector for `text` -- always via Ollama, never
    the active chat provider (see module docstring)."""
    return providers.get_provider("ollama").embed(text, model=model)


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
