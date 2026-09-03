"""Thin wrapper around a local Ollama server.

No embeddings here -- unlike agent_simulator, this project has no memory
stream to score by relevance. Just chat completion, used sparingly by
grammar.py/events.py to fill in proper nouns and prose flourishes (see
config.py's LLM_FILL_NAMES / LLM_FLOURISH_RATE); everything else is pure
grammar-driven generation that works with Ollama offline.
"""

import requests

import history_config as config

_available = None


def available() -> bool:
    """Checked once per run and cached, so a downed Ollama doesn't cost a
    failed network round-trip on every single fill attempt."""
    global _available
    if _available is None:
        try:
            requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=2)
            _available = True
        except requests.exceptions.RequestException:
            _available = False
    return _available


def chat(messages, model=None, temperature=0.7, context_tokens=None) -> str:
    """Send a chat-style prompt to Ollama and return the reply text."""
    resp = requests.post(
        f"{config.OLLAMA_HOST}/api/chat",
        json={
            "model": model or config.CHAT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": context_tokens or config.CHAT_CONTEXT_TOKENS,
            },
            "think": config.ENABLE_THINKING,
        },
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def complete(prompt: str, model=None, temperature=0.7, context_tokens=None) -> str:
    """Convenience wrapper for a single user-turn prompt."""
    return chat([{"role": "user", "content": prompt}], model=model,
                temperature=temperature, context_tokens=context_tokens)


def list_models() -> list:
    """Names of every model Ollama currently has pulled."""
    resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
    resp.raise_for_status()
    return sorted(m["name"] for m in resp.json().get("models", []))


def check_connection():
    """Raise a clear error early if Ollama or the configured model isn't ready."""
    try:
        resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Could not reach Ollama at {config.OLLAMA_HOST}. Is `ollama serve` running?"
        ) from e

    available_models = {m["name"] for m in resp.json().get("models", [])}
    available_bases = {name.split(":")[0] for name in available_models}
    base = config.CHAT_MODEL.split(":")[0]
    if config.CHAT_MODEL not in available_models and base not in available_bases:
        raise RuntimeError(
            f"Model '{config.CHAT_MODEL}' is not pulled. Run: ollama pull {config.CHAT_MODEL}"
        )
