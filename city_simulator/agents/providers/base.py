"""The provider interface every agent LLM backend implements. `ollama.py`
is the default (a local Ollama server); `claude.py` talks to the Claude
API instead. See providers/__init__.py's get_provider() for the swap
point. Embeddings are NOT part of this interface -- memory.py's relevance
scoring always goes through ollama.py's embed(), regardless of which chat
provider is active, since there's no Claude equivalent (see agents/llm.py).
"""


class Provider:
    def chat(self, messages: list, model: str = None, temperature: float = 0.7,
              context_tokens: int = None) -> str:
        """`messages` is [{"role": "user"|"assistant"|"system", "content": str}, ...].
        Returns the reply text."""
        raise NotImplementedError

    def list_models(self) -> list:
        """Model names/ids for a UI picker."""
        raise NotImplementedError

    def check_connection(self):
        """Raise a clear RuntimeError early if this provider isn't ready
        to serve chat() calls (unreachable server, missing API key, model
        not pulled, etc.)."""
        raise NotImplementedError


# --- Async interface (CITY mode's agents/gateway.py only) -----------------
# Everything below is additive: SCENE mode never calls it, and the sync
# chat()/list_models()/check_connection() above are unchanged.

class ProviderHTTPError(Exception):
    """A non-2xx reply. `retryable` is True for rate limits, overload and
    server errors (429/500/502/503/504/529)."""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.retryable = status in (408, 429, 500, 502, 503, 504, 529)


class SchemaUnsupported(Exception):
    """The server rejected the native JSON-schema field -- the gateway
    falls back to describing the schema in the prompt."""


class Reply:
    """One async generation: the text plus token counts (estimated from
    length when the server doesn't report usage)."""

    __slots__ = ("text", "tokens_in", "tokens_out")

    def __init__(self, text: str, tokens_in: int = 0, tokens_out: int = 0):
        self.text = text
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out


class AsyncCapabilities:
    """Capability flags the gateway reads. A provider class overrides
    these; a Backend (agents/gateway.py) can override them again per run
    (e.g. an OpenAI-compatible server without schema support)."""

    # A native way to constrain the reply to a JSON schema (Ollama
    # `format`, vLLM `guided_json`/`response_format`, llama.cpp
    # `json_schema`). Without it the schema goes in the prompt.
    supports_json_schema = False
    # How many requests this kind of backend should get at once by default.
    max_concurrency = 4
    # Reuses the KV cache across requests that share a prompt prefix, so
    # submitting same-prefix requests together pays off.
    supports_prefix_cache = False
