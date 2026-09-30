"""The async inference layer CITY mode runs on -- next to llm.py, not
instead of it. SCENE mode never imports this; llm.py's sync API is
unchanged.

One asyncio loop runs inside the CITY job thread with one shared
httpx.AsyncClient. Two calls do the work:

    results = await gateway.generate_many(requests)   # order-preserving
    vectors = await gateway.embed_many(texts)         # batched /api/embed

A request (LLMRequest) names its agent and tier; the tier picks a Backend
(provider + base URL + model + limits). What happens to each request:

- It waits for a slot on its backend's AIMD limiter: at most the backend's
  max_concurrency in flight; a 429/503/timeout halves the allowance
  (multiplicative decrease), each success grows it back by ~1/limit
  (additive increase), never past the cap.
- Retryable failures (429, 5xx, timeouts, dropped connections) retry with
  exponential backoff plus jitter. A request that still fails comes back
  as LLMResult(ok=False, error=...) -- it never raises and never fails the
  rest of the batch.
- A request with a JSON schema uses the backend's native constraint when
  it has one (Ollama `format`, vLLM/SGLang `response_format`/`guided_json`,
  llama.cpp `json_schema`); otherwise the schema is described in the
  prompt. The reply is parsed and validated strictly; one repair prompt is
  allowed before it counts as a failure. A server that rejects the native
  field is switched to the prompt path for the rest of the run.
- Prompts are built from parts in a fixed order -- shared city/era/rules
  prefix, tier instructions, identity, per-call specifics -- and a batch is
  submitted sorted by prefix, so a server with prefix caching reuses the
  KV cache across neighbours. Results still come back in request order.

Every call is counted (requests, retries, failures, tokens, time) in
`stats`; take_stats() returns and resets them, once per wave.
"""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import hashlib
import json
import random
import re
import time
from typing import Any, Optional

import httpx

from . import config as scene_config
from .city import config as ccfg
from .providers import get_provider
from .providers.base import ProviderHTTPError, SchemaUnsupported


# --- Requests, results, backends ------------------------------------------------------

@dataclasses.dataclass
class LLMRequest:
    agent: str
    tier: str                          # "hero" | "background" (a key of Gateway.backends)
    prompt_parts: list                 # [prefix, tier instructions, identity, specifics]
    schema: Optional[dict] = None
    max_tokens: int = 256
    temperature: float = 0.7
    seed: Optional[int] = None
    kind: str = ""                     # what the call is for ("plan", "react", ...), for stats


@dataclasses.dataclass
class LLMResult:
    ok: bool
    text: str = ""
    data: Any = None                   # the parsed JSON, for a request with a schema
    error: Optional[str] = None        # "timeout" | "http_429" | "http_500" | "schema" | "connection" | ...
    attempts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0


@dataclasses.dataclass
class Backend:
    provider: str                      # "ollama" | "openai" | "claude"
    model: str
    base_url: str
    max_concurrency: int = 4
    context_tokens: int = 4096
    api_key: str = ""
    timeout: float = ccfg.REQUEST_TIMEOUT_SECONDS
    # How an "openai" backend sends a schema: "response_format" (OpenAI
    # standard), "guided_json" (vLLM's own), "json_schema" (llama.cpp),
    # "none" (mlx_lm.server: describe it in the prompt). Ignored otherwise.
    schema_mode: str = "response_format"
    # None = the provider class's flag (see providers/base.AsyncCapabilities).
    native_schema: Optional[bool] = None

    def impl(self):
        return get_provider(self.provider)

    def uses_native_schema(self) -> bool:
        if self.native_schema is not None:
            return self.native_schema
        if self.provider == "openai" and self.schema_mode == "none":
            return False
        return self.impl().supports_json_schema

    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def backends_for_profile(profile: dict, hero_provider: str = None, hero_model: str = None,
                         background_provider: str = None, background_model: str = None) -> dict:
    """{"hero": Backend, "background": Backend} from a hardware.city_profile()
    dict plus the City Simulation node's per-tier overrides."""
    def make(provider, model, base_override):
        provider = provider or profile["provider"]
        if provider == "ollama":
            base_url = scene_config.OLLAMA_HOST
        elif provider == "openai":
            base_url = base_override or scene_config.OPENAI_COMPAT_BASE_URL
        else:
            base_url = "https://api.anthropic.com/v1/messages"
        limit = profile["max_concurrency"] if provider == profile["provider"] else get_provider(provider).max_concurrency
        return Backend(
            provider=provider, model=model, base_url=base_url.rstrip("/"),
            max_concurrency=limit, context_tokens=profile["context_tokens"],
            api_key={"openai": scene_config.OPENAI_COMPAT_API_KEY,
                     "claude": scene_config.ANTHROPIC_API_KEY or ""}.get(provider, ""),
            schema_mode=profile.get("schema_mode", "response_format") if provider == "openai" else "native",
        )

    def default_model(provider, tier_model):
        if provider and provider != profile["provider"]:
            return {"claude": scene_config.CLAUDE_MODEL, "openai": scene_config.OPENAI_COMPAT_MODEL or tier_model,
                    "ollama": scene_config.CHAT_MODEL}[provider]
        return tier_model

    return {
        "hero": make(hero_provider, hero_model or default_model(hero_provider, profile["hero_model"]), ccfg.HERO_BASE_URL),
        "background": make(background_provider,
                           background_model or default_model(background_provider, profile["background_model"]),
                           ccfg.BACKGROUND_BASE_URL),
    }


# --- AIMD concurrency limiter --------------------------------------------------------

class AIMDLimiter:
    """At most `limit` holders at once, FIFO. `limit` starts at the
    backend's max_concurrency, halves on backpressure, and climbs back
    by 1/limit per success (about +1 per full window)."""

    def __init__(self, max_limit: int):
        self.max_limit = max(1, int(max_limit))
        self.limit = float(self.max_limit)
        self.in_flight = 0
        self.peak = 0
        self._waiters = collections.deque()

    async def acquire(self):
        if self.in_flight < int(self.limit) and not self._waiters:
            self._take()
            return
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release()        # the slot was handed over just as we were cancelled
            raise

    def _take(self):
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)

    def release(self):
        self.in_flight -= 1
        self._wake()

    def _wake(self):
        while self._waiters and self.in_flight < int(self.limit):
            fut = self._waiters.popleft()
            if not fut.done():
                self._take()
                fut.set_result(None)

    def on_success(self):
        if self.limit < self.max_limit:
            self.limit = min(float(self.max_limit), self.limit + 1.0 / self.limit)
            self._wake()

    def on_backpressure(self):
        self.limit = max(1.0, self.limit / 2)


# --- JSON parsing / validation ----------------------------------------------------------

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json(text: str, schema: dict):
    """(value, None) or (None, error). Accepts a bare JSON value, one in a
    code fence, or the first JSON object/array embedded in prose -- but
    whatever comes out must validate against `schema`."""
    body = _FENCE.sub("", text.strip()).strip()
    try:
        value = json.loads(body)
    except ValueError:
        opener = "[" if schema.get("type") == "array" else "{"
        closer = "]" if opener == "[" else "}"
        start, end = body.find(opener), body.rfind(closer)
        if start < 0 or end <= start:
            return None, "no JSON found in the reply"
        try:
            value = json.loads(body[start:end + 1])
        except ValueError as e:
            return None, f"invalid JSON ({e})"
    error = validate(value, schema)
    return (None, error) if error else (value, None)


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool,
          "integer": int, "number": (int, float), "null": type(None)}


def validate(value, schema: dict, path: str = "$") -> Optional[str]:
    """A small JSON-schema subset: type, properties, required, items,
    enum, minItems, maxItems. Returns the first problem, or None."""
    expected = schema.get("type")
    if expected:
        kinds = expected if isinstance(expected, list) else [expected]
        if not any(isinstance(value, _TYPES[k]) and not (k in ("integer", "number") and isinstance(value, bool))
                   for k in kinds):
            return f"{path} should be {expected}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} should be one of {schema['enum']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"{path} is missing {key!r}"
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                problem = validate(value[key], sub, f"{path}.{key}")
                if problem:
                    return problem
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            return f"{path} needs at least {schema['minItems']} items"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path} has more than {schema['maxItems']} items"
        if "items" in schema:
            for i, item in enumerate(value):
                problem = validate(item, schema["items"], f"{path}[{i}]")
                if problem:
                    return problem
    return None


def _schema_instructions(schema: dict) -> str:
    return ("Reply with ONLY a JSON value -- no prose, no code fences -- that matches this JSON Schema:\n"
            + json.dumps(schema))


# --- The gateway ----------------------------------------------------------------------------

def _new_stats() -> dict:
    return {"requests": 0, "ok": 0, "failures": 0, "retries": 0, "repairs": 0, "backpressure": 0,
            "tokens_in": 0, "tokens_out": 0, "busy_seconds": 0.0, "by_tier": collections.Counter(),
            "by_kind": collections.Counter(), "errors": collections.Counter()}


class Gateway:
    """Use as `async with Gateway(backends) as gw:` inside the loop that
    will make the calls. `transport` lets tests (and the headless
    benchmark) swap in an httpx.MockTransport stub server."""

    def __init__(self, backends: dict, embed_base_url: str = None, embed_model: str = None,
                 transport: httpx.AsyncBaseTransport = None, max_retries: int = ccfg.MAX_RETRIES,
                 backoff_base: float = ccfg.BACKOFF_BASE_SECONDS, rng: random.Random = None):
        self.backends = backends
        self.embed_base_url = (embed_base_url or scene_config.OLLAMA_HOST).rstrip("/")
        self.embed_model = embed_model or ccfg.EMBED_MODEL
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._rng = rng or random.Random()
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        # One limiter per distinct server+model: two tiers on the same
        # server share its capacity.
        self._limiters = {}
        for b in backends.values():
            key = (b.base_url, b.model)
            if key not in self._limiters:
                self._limiters[key] = AIMDLimiter(b.max_concurrency)
            else:
                self._limiters[key].max_limit = max(self._limiters[key].max_limit, b.max_concurrency)
        self._embed_limiter = AIMDLimiter(ccfg.EMBED_MAX_CONCURRENCY)
        self.stats = _new_stats()
        self.totals = _new_stats()

    async def __aenter__(self):
        limits = httpx.Limits(max_connections=None, max_keepalive_connections=64)
        self._client = httpx.AsyncClient(transport=self._transport, limits=limits,
                                         timeout=ccfg.REQUEST_TIMEOUT_SECONDS)
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()
        self._client = None

    def limiter_for(self, tier: str) -> AIMDLimiter:
        b = self.backends[tier]
        return self._limiters[(b.base_url, b.model)]

    def take_stats(self) -> dict:
        """This wave's counters (then reset). by_tier/by_kind count requests."""
        out = self.stats
        self.stats = _new_stats()
        return {**out, "by_tier": dict(out["by_tier"]), "by_kind": dict(out["by_kind"]),
                "errors": dict(out["errors"])}

    def _count(self, key: str, n=1):
        self.stats[key] += n
        self.totals[key] += n

    # -- generation -----------------------------------------------------------------

    async def generate_many(self, requests: list) -> list:
        """One LLMResult per request, in the same order. Submission order
        is sorted by prompt prefix (see module docstring)."""
        if not requests:
            return []
        order = sorted(range(len(requests)), key=lambda i: _prefix_key(requests[i]))
        tasks = {}
        for i in order:
            tasks[i] = asyncio.ensure_future(self._one(requests[i]))
        return list(await asyncio.gather(*(tasks[i] for i in range(len(requests)))))

    async def _one(self, req: LLMRequest) -> LLMResult:
        backend = self.backends[req.tier]
        limiter = self.limiter_for(req.tier)
        started = time.monotonic()
        self.stats["by_tier"][req.tier] += 1
        self.totals["by_tier"][req.tier] += 1
        self.stats["by_kind"][req.kind or "other"] += 1
        self.totals["by_kind"][req.kind or "other"] += 1
        prompt = "\n\n".join(p for p in req.prompt_parts if p)
        messages = None
        repaired = False
        attempts = 0
        tokens_in = tokens_out = 0
        last_error = "unknown"
        retries_left = self.max_retries

        while True:
            native = req.schema is not None and backend.uses_native_schema()
            if messages is None:
                content = prompt if (req.schema is None or native) else f"{prompt}\n\n{_schema_instructions(req.schema)}"
                messages = [{"role": "user", "content": content}]
            attempts += 1
            self._count("requests")
            await limiter.acquire()
            t0 = time.monotonic()
            error = None
            reply = None
            try:
                reply = await asyncio.wait_for(
                    backend.impl().agenerate(self._client, backend, messages, max_tokens=req.max_tokens,
                                             temperature=req.temperature, seed=req.seed,
                                             schema=req.schema if native else None),
                    timeout=backend.timeout)
            except SchemaUnsupported:
                backend.native_schema = False
                messages = None
                error = "schema_unsupported"
            except asyncio.TimeoutError:
                limiter.on_backpressure()
                self._count("backpressure")
                error = "timeout"
            except ProviderHTTPError as e:
                if e.status in (429, 503, 529):
                    limiter.on_backpressure()
                    self._count("backpressure")
                error = f"http_{e.status}" if e.retryable else f"http_{e.status}_fatal"
            except (httpx.TransportError, OSError):
                error = "connection"
            except Exception as e:     # a provider bug or malformed reply: fail this request only
                error = f"error:{type(e).__name__}"
            finally:
                limiter.release()
                self._count("busy_seconds", time.monotonic() - t0)

            if error == "schema_unsupported":
                continue               # immediately retry with the schema in the prompt
            if reply is not None:
                limiter.on_success()
                tokens_in += reply.tokens_in
                tokens_out += reply.tokens_out
                self._count("tokens_in", reply.tokens_in)
                self._count("tokens_out", reply.tokens_out)
                if req.schema is None:
                    return self._done(LLMResult(True, reply.text, None, None, attempts, tokens_in, tokens_out,
                                                time.monotonic() - started))
                data, problem = parse_json(reply.text, req.schema)
                if problem is None:
                    return self._done(LLMResult(True, reply.text, data, None, attempts, tokens_in, tokens_out,
                                                time.monotonic() - started))
                if repaired:
                    last_error = "schema"
                    break
                repaired = True
                self._count("repairs")
                messages = messages + [
                    {"role": "assistant", "content": reply.text},
                    {"role": "user", "content": f"That reply was not valid: {problem}. "
                                                f"{_schema_instructions(req.schema)}"},
                ]
                continue

            last_error = error
            if error.endswith("_fatal") or retries_left <= 0:
                break
            retries_left -= 1
            self._count("retries")
            delay = min(ccfg.BACKOFF_CAP_SECONDS, self.backoff_base * 2 ** (self.max_retries - retries_left - 1))
            await asyncio.sleep(delay * self._rng.uniform(0.5, 1.5))

        self.stats["errors"][last_error] += 1
        self.totals["errors"][last_error] += 1
        return self._done(LLMResult(False, "", None, last_error, attempts, tokens_in, tokens_out,
                                    time.monotonic() - started))

    def _done(self, result: LLMResult) -> LLMResult:
        self._count("ok" if result.ok else "failures")
        return result

    # -- embeddings -------------------------------------------------------------------

    async def embed_many(self, texts: list) -> list:
        """One vector per text, in order (duplicates embedded once). A batch
        that still fails after retries gives its texts empty vectors,
        which retrieval scores as zero relevance, rather than failing."""
        if not texts:
            return []
        unique = list(dict.fromkeys(texts))
        batches = [unique[i:i + ccfg.EMBED_BATCH_SIZE] for i in range(0, len(unique), ccfg.EMBED_BATCH_SIZE)]
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        vectors = {}
        for batch, vecs in zip(batches, results):
            vectors.update(zip(batch, vecs))
        return [vectors[t] for t in texts]

    async def _embed_batch(self, batch: list) -> list:
        ollama = get_provider("ollama")
        for attempt in range(self.max_retries + 1):
            await self._embed_limiter.acquire()
            self._count("requests")
            self.stats["by_kind"]["embed"] += 1
            self.totals["by_kind"]["embed"] += 1
            try:
                return await ollama.aembed_many(self._client, self.embed_base_url, self.embed_model, batch)
            except (ProviderHTTPError, httpx.TransportError, asyncio.TimeoutError, OSError):
                pass
            finally:
                self._embed_limiter.release()
            if attempt < self.max_retries:
                self._count("retries")
                await asyncio.sleep(self.backoff_base * 2 ** attempt * self._rng.uniform(0.5, 1.5))
        self._count("failures")
        self.stats["errors"]["embed"] += 1
        self.totals["errors"]["embed"] += 1
        return [[] for _ in batch]

    # -- preflight ------------------------------------------------------------------

    async def available_models(self, backend: Backend) -> list:
        impl = backend.impl()
        if backend.provider == "ollama":
            return await impl.alist_models(self._client, backend.base_url)
        if backend.provider == "openai":
            return await impl.alist_models(self._client, backend.base_url, backend.api_key)
        return await impl.alist_models(self._client)


def _prefix_key(req: LLMRequest) -> tuple:
    """Sort key grouping requests that share leading prompt parts: the
    hashes of every part but the last (the per-call specifics)."""
    return tuple(hashlib.md5((p or "").encode()).hexdigest() for p in req.prompt_parts[:-1])


def run_sync(coro):
    """Run a coroutine to completion on a fresh event loop -- for callers
    on a plain thread (a Flask request) that need one gateway call."""
    return asyncio.run(coro)
