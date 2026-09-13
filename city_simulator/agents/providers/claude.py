"""Claude-API-backed Provider. Talks directly to the Messages API
(https://api.anthropic.com/v1/messages) via `requests` -- no `anthropic`
SDK dependency, matching visuals/providers/fal.py's precedent of raw REST
over a vendor SDK.

Note `context_tokens` means something different here than it does for
Ollama: Ollama's num_ctx caps the *input* context window; Claude's
max_tokens caps *output* length. This provider treats the incoming
`context_tokens` param as a max_tokens override for calls that need more
room (e.g. treatment.py's whole-transcript summary), not an input-window
setting -- there's no equivalent knob to set on this side for input size.

Has no embeddings endpoint -- agents/llm.py's embed() always goes to
ollama.py regardless of which chat provider is selected.

`temperature` is accepted by every call site here (it matters for the
Ollama provider) but silently dropped by chat() below, not forwarded --
current-generation Claude models reject the parameter outright with a 400
("`temperature` is deprecated for this model"), confirmed directly
against the live API rather than assumed from docs.
"""

import time

import requests

from .. import config
from .base import Provider

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_MAX_RETRIES = 3
_RETRY_STATUS_CODES = (429, 500, 502, 503, 529)

# No "list what's installed" endpoint the way Ollama has -- this is just
# the current model lineup, for a UI picker's suggestions. Any model id
# can still be typed in directly; this isn't a hard allowlist.
_KNOWN_MODELS = [
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-haiku-4-5-20251001",
    "claude-fable-5",
]


def _require_api_key() -> str:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set -- get a key from "
            "https://console.anthropic.com and `export ANTHROPIC_API_KEY=...` "
            "(or add it to .env) before running agents against Claude."
        )
    return config.ANTHROPIC_API_KEY


def _check_response(resp: requests.Response):
    """requests' default raise_for_status() message is just the status
    line -- Anthropic's actual explanation (bad key, overloaded, invalid
    request, ...) is in the response body, which this surfaces instead of
    hiding."""
    if not resp.ok:
        raise requests.exceptions.HTTPError(
            f"Claude API returned {resp.status_code} {resp.reason} for {resp.url}: {resp.text}",
            response=resp,
        )


class ClaudeProvider(Provider):
    def chat(self, messages: list, model: str = None, temperature: float = 0.7,
              context_tokens: int = None) -> str:
        api_key = _require_api_key()

        # A "system" role isn't a message here -- it's a separate top-level
        # field. Nothing in this codebase sends one today (every call site
        # goes through llm.complete(), a single user-turn message), but
        # lifting it out here keeps this a correct general chat() rather
        # than one that would silently mishandle a system message later.
        system = None
        api_messages = []
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content")
            else:
                api_messages.append(m)

        body = {
            "model": model or config.CLAUDE_MODEL,
            "max_tokens": context_tokens or config.CLAUDE_MAX_TOKENS,
            "messages": api_messages,
        }
        # `temperature` is deprecated on current-generation Claude models --
        # sending it at all is a 400 ("`temperature` is deprecated for this
        # model"), not just ignored, confirmed directly against the live
        # API. Every call site here still passes one (it's meaningful for
        # the Ollama provider), so it's accepted and silently dropped
        # rather than plumbed through, instead of pushing a
        # provider-specific exception up through agent.py/planning.py/etc.
        if system:
            body["system"] = system

        headers = {
            "x-api-key": api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

        delay = 1.0
        for attempt in range(_MAX_RETRIES + 1):
            resp = requests.post(_API_URL, json=body, headers=headers,
                                  timeout=config.REQUEST_TIMEOUT_SECONDS)
            if resp.status_code in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            _check_response(resp)
            data = resp.json()
            return "".join(
                block.get("text", "") for block in data.get("content", [])
                if block.get("type") == "text"
            ).strip()

    def list_models(self) -> list:
        return list(_KNOWN_MODELS)

    def check_connection(self):
        _require_api_key()
