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
from .base import Provider

_RETRY_STATUS_CODES = (429, 500, 502, 503)
_MAX_RETRIES = 3
# Reasoning models served this way often prefix their answer with a
# <think>...</think> block; every caller here wants just the answer.
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatProvider(Provider):
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
