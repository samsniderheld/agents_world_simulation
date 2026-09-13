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
