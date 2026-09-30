"""Provider for any server that speaks the OpenAI chat-completions API:
mlx_lm.server (Apple Silicon), vLLM, SGLang, LM Studio -- or OpenAI itself.
Point config.OPENAI_COMPAT_BASE_URL (env OPENAI_COMPAT_BASE_URL, including
the /v1 prefix) at it. These servers batch concurrent requests, which is
what makes the tick loop's parallel calls pay off (see config.MAX_CONCURRENCY).

Raw REST via `requests`, like claude.py -- no SDK dependency. Like Claude,
`context_tokens` here caps *output* (max_tokens), not the input window.
Embeddings still come from Ollama (agents/llm.py), so an Ollama with the
embedding model pulled is needed alongside this.
"""

import re
import time

import requests

from .. import config
from .base import AsyncCapabilities, Provider, ProviderHTTPError, Reply, SchemaUnsupported

_RETRY_STATUS_CODES = (429, 500, 502, 503)
_MAX_RETRIES = 3
# Reasoning models served this way often prefix their answer with a
# <think>...</think> block; every caller here wants just the answer.
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatProvider(Provider, AsyncCapabilities):
    # Async capability flags (CITY mode's gateway). vLLM, SGLang and
    # llama.cpp constrain output to a JSON schema natively (mlx_lm.server
    # doesn't -- a Backend with schema_mode "none" covers that, and a
    # server that rejects the field is detected and falls back); all of
    # them batch concurrent requests and cache shared prompt prefixes.
    supports_json_schema = True
    max_concurrency = 64
    supports_prefix_cache = True

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if config.OPENAI_COMPAT_API_KEY:
            headers["Authorization"] = f"Bearer {config.OPENAI_COMPAT_API_KEY}"
        return headers

    def _model(self, model: str = None) -> str:
        if model or config.OPENAI_COMPAT_MODEL:
            return model or config.OPENAI_COMPAT_MODEL
        models = self.list_models()
        if not models:
            raise RuntimeError(f"The server at {config.OPENAI_COMPAT_BASE_URL} lists no models.")
        return models[0]

    def chat(self, messages: list, model: str = None, temperature: float = 0.7,
             context_tokens: int = None) -> str:
        body = {
            "model": self._model(model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": context_tokens or config.OPENAI_COMPAT_MAX_TOKENS,
        }
        for attempt in range(_MAX_RETRIES + 1):
            resp = requests.post(
                f"{config.OPENAI_COMPAT_BASE_URL}/chat/completions",
                json=body, headers=self._headers(), timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            if resp.status_code in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            if not resp.ok:
                raise RuntimeError(f"{config.OPENAI_COMPAT_BASE_URL} returned {resp.status_code}: {resp.text[:300]}")
            content = resp.json()["choices"][0]["message"].get("content") or ""
            return _THINK.sub("", content).strip()
        raise RuntimeError("unreachable")

    def list_models(self) -> list:
        resp = requests.get(f"{config.OPENAI_COMPAT_BASE_URL}/models", headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return [m["id"] for m in resp.json().get("data", [])]

    def check_connection(self):
        try:
            models = self.list_models()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"Could not reach an OpenAI-compatible server at {config.OPENAI_COMPAT_BASE_URL}. "
                "Start one (e.g. `mlx_lm.server --model <model>`, `vllm serve <model>`, or SGLang) "
                "or set OPENAI_COMPAT_BASE_URL."
            ) from e
        wanted = config.OPENAI_COMPAT_MODEL
        if wanted and wanted not in models:
            raise RuntimeError(f"Model '{wanted}' isn't served at {config.OPENAI_COMPAT_BASE_URL} (it has: {', '.join(models) or 'none'}).")

    # --- async (CITY mode's agents/gateway.py) ---------------------------

    async def agenerate(self, client, backend, messages: list, *, max_tokens: int = 256,
                        temperature: float = 0.7, seed: int = None, schema: dict = None) -> Reply:
        body = {"model": backend.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if seed is not None:
            body["seed"] = seed
        mode = backend.schema_mode
        if schema is not None:
            if mode == "guided_json":        # vLLM's own extra parameter
                body["guided_json"] = schema
            elif mode == "json_schema":      # llama.cpp server
                body["json_schema"] = schema
            else:                            # OpenAI standard; vLLM, SGLang, llama.cpp
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "reply", "schema": schema}}
        headers = {"Content-Type": "application/json"}
        if backend.api_key:
            headers["Authorization"] = f"Bearer {backend.api_key}"
        resp = await client.post(f"{backend.base_url}/chat/completions", json=body, headers=headers,
                                 timeout=backend.timeout)
        if resp.status_code == 400 and schema is not None and any(
                k in resp.text for k in ("response_format", "json_schema", "guided", "grammar")):
            raise SchemaUnsupported(resp.text[:300])
        if resp.status_code >= 400:
            raise ProviderHTTPError(resp.status_code, resp.text[:300])
        data = resp.json()
        text = _THINK.sub("", (data["choices"][0]["message"].get("content") or "")).strip()
        usage = data.get("usage") or {}
        return Reply(text, usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or len(text) // 4)

    async def alist_models(self, client, base_url: str, api_key: str = "") -> list:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = await client.get(f"{base_url}/models", headers=headers, timeout=10)
        if resp.status_code >= 400:
            raise ProviderHTTPError(resp.status_code, resp.text[:300])
        return [m["id"] for m in resp.json().get("data", [])]
