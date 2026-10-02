"""Local-Ollama-backed Provider -- the default. Also the sole home of
embed(): memory.py's relevance scoring always calls back into *this*
provider for embeddings regardless of which chat provider is active (see
agents/llm.py's dispatcher), since Ollama's nomic-embed-text has no
Claude-API equivalent.
"""

import requests

from .. import config
from .base import AsyncCapabilities, Provider, ProviderHTTPError, Reply


class OllamaProvider(Provider, AsyncCapabilities):
    # Async capability flags (CITY mode's gateway). Ollama >= 0.5 takes a
    # JSON schema as `format`; it queues past OLLAMA_NUM_PARALLEL, and
    # keeps one KV cache per parallel slot, so shared prefixes help only a
    # little.
    supports_json_schema = True
    max_concurrency = 4
    supports_prefix_cache = False

    def chat(self, messages: list, model: str = None, temperature: float = 0.7,
              context_tokens: int = None) -> str:
        """Explicitly caps num_ctx (see config.CHAT_CONTEXT_TOKENS) rather
        than letting Ollama default to the model's max context -- otherwise
        it allocates a KV cache sized for that max on every call, which can
        push a large model into swap even for a one-line prompt. Pass
        `context_tokens` to override that default for calls with unusually
        long prompts (e.g. a full simulation transcript)."""
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

    def list_models(self) -> list:
        """Names of every model Ollama currently has pulled, for a UI picker."""
        resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
        return sorted(m["name"] for m in resp.json().get("models", []))

    def check_connection(self):
        """Raise a clear error early if Ollama or the configured chat/embed
        models aren't ready."""
        available = self._pulled_models()
        for required in (config.CHAT_MODEL, config.EMBED_MODEL):
            self._require_pulled(required, available)

    def check_embed_model(self):
        """Same as check_connection(), but only checks the embedding
        model -- used when the active *chat* provider isn't Ollama, so a
        Claude-mode run isn't wrongly blocked on CHAT_MODEL not being
        pulled locally (it's never used in that mode)."""
        self._require_pulled(config.EMBED_MODEL, self._pulled_models())

    def _pulled_models(self) -> set:
        try:
            resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"Could not reach Ollama at {config.OLLAMA_HOST}. Is `ollama serve` running?"
            ) from e
        return {m["name"] for m in resp.json().get("models", [])}

    def _require_pulled(self, model_name: str, available: set):
        base = model_name.split(":")[0]
        available_bases = {name.split(":")[0] for name in available}
        if model_name not in available and base not in available_bases:
            raise RuntimeError(f"Model '{model_name}' is not pulled. Run: ollama pull {model_name}")

    def embed_many(self, texts: list, model: str = None) -> list:
        """Embedding vectors for several texts in one request (Ollama's
        /api/embed takes a list). Falls back to one request per text on an
        Ollama too old to have that endpoint."""
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/embed",
            json={"model": model or config.EMBED_MODEL, "input": texts},
            timeout=120,
        )
        if resp.status_code == 404:
            return [self.embed(t, model=model) for t in texts]
        resp.raise_for_status()
        return resp.json()["embeddings"]

    def embed(self, text: str, model: str = None) -> list:
        """Return an embedding vector for `text`."""
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/embeddings",
            json={"model": model or config.EMBED_MODEL, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    # --- async (CITY mode's agents/gateway.py) ---------------------------
    # Take the target explicitly (a gateway Backend: base_url, model,
    # context_tokens) instead of reading config, so the two CITY tiers can
    # use different models, and a CITY run never changes what SCENE uses.

    async def agenerate(self, client, backend, messages: list, *, max_tokens: int = 256,
                        temperature: float = 0.7, seed: int = None, schema: dict = None) -> Reply:
        options = {"temperature": temperature, "num_ctx": backend.context_tokens, "num_predict": max_tokens}
        if seed is not None:
            options["seed"] = seed
        body = {"model": backend.model, "messages": messages, "stream": False,
                "options": options, "think": config.ENABLE_THINKING}
        if schema is not None:
            body["format"] = schema
        resp = await client.post(f"{backend.base_url}/api/chat", json=body, timeout=backend.timeout)
        if resp.status_code >= 400:
            raise ProviderHTTPError(resp.status_code, resp.text[:300])
        data = resp.json()
        text = (data.get("message") or {}).get("content", "").strip()
        return Reply(text, data.get("prompt_eval_count") or 0, data.get("eval_count") or len(text) // 4)

    async def aembed_many(self, client, base_url: str, model: str, texts: list, timeout: float = 120) -> list:
        resp = await client.post(f"{base_url}/api/embed", json={"model": model, "input": texts}, timeout=timeout)
        if resp.status_code >= 400:
            raise ProviderHTTPError(resp.status_code, resp.text[:300])
        return resp.json()["embeddings"]

    async def alist_models(self, client, base_url: str) -> list:
        resp = await client.get(f"{base_url}/api/tags", timeout=10)
        if resp.status_code >= 400:
            raise ProviderHTTPError(resp.status_code, resp.text[:300])
        return sorted(m["name"] for m in resp.json().get("models", []))
