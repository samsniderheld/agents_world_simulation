"""A fake LLM server for tests and the headless benchmark: an
httpx.MockTransport that answers the Ollama (/api/chat, /api/embed,
/api/tags) and OpenAI-compatible (/v1/chat/completions, /v1/models)
endpoints the gateway calls -- with configurable latency, a failure rate,
a 429 rate, and whether it honours a native JSON schema. It records how
many requests were in flight at once, so tests can check the concurrency
cap.

    server = StubServer(latency=0.05, failure_rate=0.1)
    gateway = Gateway(backends, transport=server.transport())

Replies: `reply_fn(prompt, schema) -> str` if given; otherwise a request
with a schema gets a minimal valid instance of it (see instance_of), and
one without gets a short sentence. CITY's benchmark passes
agents.city.prompts' stub replier so every kind of call gets a plausible
answer.
"""

import asyncio
import hashlib
import json
import random

import httpx

# How agents/gateway.py introduces a schema it describes in the prompt.
_SCHEMA_MARKER = "that matches this JSON Schema:\n"


def instance_of(schema: dict, seed: int = 0):
    """The smallest value that validates against `schema` (the subset
    agents/gateway.validate understands), varied a little by `seed`."""
    if "enum" in schema:
        return schema["enum"][seed % len(schema["enum"])]
    kind = schema.get("type")
    kind = kind[0] if isinstance(kind, list) else kind
    if kind == "object":
        props = schema.get("properties") or {}
        return {k: instance_of(props.get(k, {"type": "string"}), seed + i) for i, k in enumerate(schema.get("required", props))}
    if kind == "array":
        n = max(schema.get("minItems", 1), 1)
        if "maxItems" in schema:
            n = min(n, schema["maxItems"])
        return [instance_of(schema.get("items", {"type": "string"}), seed + i) for i in range(n)]
    if kind == "integer":
        return 1 + seed % 5
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    return f"stub text {seed % 97}"


class StubServer:
    def __init__(self, latency: float = 0.0, jitter: float = 0.0, failure_rate: float = 0.0,
                 rate_limit_rate: float = 0.0, supports_schema: bool = True, reply_fn=None,
                 embed_dim: int = 16, seed: int = 0, models=("stub-hero", "stub-background")):
        self.latency = latency
        self.jitter = jitter
        self.failure_rate = failure_rate
        self.rate_limit_rate = rate_limit_rate
        self.supports_schema = supports_schema
        self.reply_fn = reply_fn
        self.embed_dim = embed_dim
        self.models = list(models)
        self._rng = random.Random(seed)
        self.in_flight = 0
        self.peak = 0
        self.chat_calls = 0
        self.embed_calls = 0
        self.embedded_texts = 0
        self.failures_served = 0
        self.prompts = []
        self.bodies = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET":
            if path.endswith("/api/tags"):
                return httpx.Response(200, json={"models": [{"name": m} for m in self.models + ["nomic-embed-text:latest"]]})
            if path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
            return httpx.Response(404, json={"error": "not found"})

        body = json.loads(request.content or b"{}")
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            delay = self.latency + (self._rng.uniform(0, self.jitter) if self.jitter else 0)
            if delay:
                await asyncio.sleep(delay)
            if path.endswith("/api/embed"):
                return self._embed(body)
            roll = self._rng.random()
            if roll < self.rate_limit_rate:
                self.failures_served += 1
                return httpx.Response(429, json={"error": "rate limited"})
            if roll < self.rate_limit_rate + self.failure_rate:
                self.failures_served += 1
                return httpx.Response(503, json={"error": "overloaded"})
            return self._chat(path, body)
        finally:
            self.in_flight -= 1

    def _embed(self, body: dict) -> httpx.Response:
        texts = body.get("input") or []
        self.embed_calls += 1
        self.embedded_texts += len(texts)
        vectors = []
        for t in texts:
            h = int(hashlib.sha256(t.encode()).hexdigest(), 16)
            vectors.append([((h >> (k * 8)) % 256) / 255.0 - 0.5 for k in range(self.embed_dim)])
        return httpx.Response(200, json={"embeddings": vectors})

    def _chat(self, path: str, body: dict) -> httpx.Response:
        self.chat_calls += 1
        self.bodies.append(body)
        prompt = "\n".join(m.get("content", "") for m in body.get("messages", []))
        self.prompts.append(prompt)
        is_openai = path.endswith("/chat/completions")
        is_claude = path.endswith("/messages")
        schema = None
        if is_openai:
            if "response_format" in body:
                if not self.supports_schema:
                    return httpx.Response(400, json={"error": "response_format is not supported"})
                schema = body["response_format"]["json_schema"]["schema"]
            schema = schema or body.get("guided_json") or body.get("json_schema")
        else:
            fmt = body.get("format")
            if isinstance(fmt, dict):
                schema = fmt if self.supports_schema else None
        if schema is None and _SCHEMA_MARKER in prompt:
            # The gateway described the schema in the prompt (no native
            # support): a well-behaved model follows it.
            try:
                schema = json.loads(prompt.rsplit(_SCHEMA_MARKER, 1)[1].strip().splitlines()[0])
            except (ValueError, IndexError):
                schema = None
        seed = int(hashlib.md5(prompt.encode()).hexdigest()[:6], 16)
        if self.reply_fn:
            text = self.reply_fn(prompt, schema)
        elif schema is not None:
            text = json.dumps(instance_of(schema, seed))
        else:
            text = f"A plain reply {seed % 1000}."
        tokens_in, tokens_out = max(1, len(prompt) // 4), max(1, len(text) // 4)
        if is_claude:
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                             "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}})
        if is_openai:
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
            })
        return httpx.Response(200, json={"message": {"role": "assistant", "content": text},
                                         "prompt_eval_count": tokens_in, "eval_count": tokens_out})
