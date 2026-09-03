"""Thin wrapper around a local Ollama server.

Deliberately dependency-light (just `requests`) so the rest of the codebase
can be swapped to a different local runtime (MLX, llama.cpp) by reimplementing
just the two functions below.
"""

import requests

import agent_config as config


def chat(messages, model=None, temperature=0.7, context_tokens=None) -> str:
    """Send a chat-style prompt to Ollama and return the reply text.
    Explicitly caps num_ctx (see config.CHAT_CONTEXT_TOKENS) rather than
    letting Ollama default to the model's max context -- otherwise it
    allocates a KV cache sized for that max on every call, which can push a
    large model into swap even for a one-line prompt. Pass `context_tokens`
    to override that default for calls with unusually long prompts (e.g. a
    full simulation transcript)."""
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


def embed(text: str, model=None) -> list[float]:
    """Return an embedding vector for `text`."""
    resp = requests.post(
        f"{config.OLLAMA_HOST}/api/embeddings",
        json={"model": model or config.EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def list_models() -> list[str]:
    """Names of every model Ollama currently has pulled, for a UI picker."""
    resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
    resp.raise_for_status()
    return sorted(m["name"] for m in resp.json().get("models", []))


def check_connection():
    """Raise a clear error early if Ollama or the configured models aren't ready."""
    try:
        resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Could not reach Ollama at {config.OLLAMA_HOST}. Is `ollama serve` running?"
        ) from e

    available = {m["name"] for m in resp.json().get("models", [])}
    available_bases = {name.split(":")[0] for name in available}

    for required in (config.CHAT_MODEL, config.EMBED_MODEL):
        base = required.split(":")[0]
        if required not in available and base not in available_bases:
            raise RuntimeError(
                f"Model '{required}' is not pulled. Run: ollama pull {required}"
            )
