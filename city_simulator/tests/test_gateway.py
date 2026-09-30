"""agents/gateway.py against the stub LLM server (httpx.MockTransport)."""

import asyncio
import json
import math
import random
import unittest

import httpx

from agents.city.stub_server import StubServer
from agents.gateway import AIMDLimiter, Backend, Gateway, LLMRequest, parse_json

SCHEMA = {"type": "object", "required": ["mood", "count"],
          "properties": {"mood": {"type": "string", "enum": ["calm", "tense"]}, "count": {"type": "integer"}}}


def backend(provider="ollama", limit=4, **kw):
    base = {"ollama": "http://stub:11434", "openai": "http://stub:8000/v1",
            "claude": "http://stub/v1/messages"}[provider]
    return Backend(provider=provider, model="stub-hero", base_url=base, max_concurrency=limit, timeout=5, **kw)


def run(coro):
    return asyncio.run(coro)


async def with_gateway(server, backends, fn, **kw):
    kw.setdefault("backoff_base", 0.001)
    async with Gateway(backends, embed_base_url="http://stub:11434", transport=server.transport(),
                       rng=random.Random(0), **kw) as gw:
        return await fn(gw)


def req(i, prefix="city prefix", tier="hero", **kw):
    return LLMRequest(agent=f"a{i}", tier=tier, prompt_parts=[prefix, "tier rules", f"identity {i}", f"ask {i}"], **kw)


class GatewayTests(unittest.TestCase):
    def test_order_preserved(self):
        server = StubServer(latency=0.001, jitter=0.02, reply_fn=lambda p, s: p.strip().splitlines()[-1])
        reqs = [req(i, prefix=f"prefix {i % 3}") for i in range(60)]
        results = run(with_gateway(server, {"hero": backend(limit=8)}, lambda gw: gw.generate_many(reqs)))
        self.assertEqual([r.text for r in results], [f"ask {i}" for i in range(60)])
        self.assertTrue(all(r.ok for r in results))

    def test_concurrency_cap(self):
        server = StubServer(latency=0.02)

        async def go(gw):
            results = await gw.generate_many([req(i) for i in range(40)])
            return results, gw.limiter_for("hero").peak
        results, peak = run(with_gateway(server, {"hero": backend(limit=4)}, go))
        self.assertTrue(all(r.ok for r in results))
        self.assertLessEqual(server.peak, 4)
        self.assertLessEqual(peak, 4)
        self.assertGreaterEqual(server.peak, 3)   # and it actually used the parallelism

    def test_shared_server_shares_one_cap(self):
        server = StubServer(latency=0.02)
        shared = {"hero": backend(limit=3), "background": backend(limit=3)}
        reqs = [req(i, tier="hero" if i % 2 else "background") for i in range(30)]
        run(with_gateway(server, shared, lambda gw: gw.generate_many(reqs)))
        self.assertLessEqual(server.peak, 3)

    def test_retry_and_backpressure(self):
        server = StubServer(rate_limit_rate=0.3, seed=3)

        async def go(gw):
            results = await gw.generate_many([req(i) for i in range(40)])
            return results, gw.take_stats()
        results, stats = run(with_gateway(server, {"hero": backend(limit=8)}, go, max_retries=4))
        self.assertGreater(stats["retries"], 0)
        self.assertGreater(stats["backpressure"], 0)
        self.assertGreaterEqual(sum(r.ok for r in results), 38)

    def test_failures_are_typed_and_isolated(self):
        class Picky(StubServer):
            def _chat(self, path, body):
                if "BAD" in body["messages"][-1]["content"]:
                    return httpx.Response(500, json={"error": "boom"})
                return super()._chat(path, body)
        server = Picky()
        reqs = [req(i) for i in range(6)] + [LLMRequest("bad", "hero", ["p", "t", "i", "BAD"])]
        results = run(with_gateway(server, {"hero": backend()}, lambda gw: gw.generate_many(reqs), max_retries=2))
        self.assertTrue(all(r.ok for r in results[:6]))
        self.assertFalse(results[6].ok)
        self.assertEqual(results[6].error, "http_500")
        self.assertEqual(results[6].attempts, 3)

    def test_all_failing_never_raises(self):
        server = StubServer(failure_rate=1.0)
        results = run(with_gateway(server, {"hero": backend()}, lambda gw: gw.generate_many([req(i) for i in range(5)]),
                                   max_retries=1))
        self.assertEqual([r.error for r in results], ["http_503"] * 5)

    def test_timeout_is_a_typed_failure(self):
        server = StubServer(latency=0.5)
        slow = backend()
        slow.timeout = 0.05
        results = run(with_gateway(server, {"hero": slow}, lambda gw: gw.generate_many([req(0)]), max_retries=1))
        self.assertEqual(results[0].error, "timeout")

    def test_native_schema_ollama(self):
        server = StubServer()
        results = run(with_gateway(server, {"hero": backend()},
                                   lambda gw: gw.generate_many([req(0, schema=SCHEMA)])))
        self.assertTrue(results[0].ok)
        self.assertIn(results[0].data["mood"], ("calm", "tense"))
        self.assertEqual(server.bodies[0]["format"], SCHEMA)
        self.assertNotIn("JSON Schema", server.prompts[0])

    def test_native_schema_openai(self):
        server = StubServer()
        results = run(with_gateway(server, {"hero": backend("openai")},
                                   lambda gw: gw.generate_many([req(0, schema=SCHEMA)])))
        self.assertTrue(results[0].ok)
        self.assertEqual(server.bodies[0]["response_format"]["json_schema"]["schema"], SCHEMA)

    def test_schema_fallback_when_server_rejects_it(self):
        server = StubServer(supports_schema=False)
        b = backend("openai")

        async def go(gw):
            first = await gw.generate_many([req(0, schema=SCHEMA)])
            second = await gw.generate_many([req(1, schema=SCHEMA)])
            return first + second
        results = run(with_gateway(server, {"hero": b}, go))
        self.assertTrue(all(r.ok for r in results))
        self.assertIs(b.native_schema, False)
        self.assertIn("JSON Schema", server.prompts[-1])
        self.assertNotIn("response_format", server.bodies[-1])

    def test_schema_in_prompt_and_one_repair(self):
        def replier(prompt, schema):
            return '{"mood": "tense", "count": 2}' if "was not valid" in prompt else "sure! here you go"
        server = StubServer(reply_fn=replier)

        async def go(gw):
            results = await gw.generate_many([req(0, schema=SCHEMA)])
            return results, gw.take_stats()
        results, stats = run(with_gateway(server, {"hero": backend("claude")}, go))
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].data, {"mood": "tense", "count": 2})
        self.assertEqual(stats["repairs"], 1)

    def test_schema_failure_after_repair(self):
        server = StubServer(reply_fn=lambda p, s: '{"mood": "ecstatic", "count": 1}')
        results = run(with_gateway(server, {"hero": backend()}, lambda gw: gw.generate_many([req(0, schema=SCHEMA)])))
        self.assertFalse(results[0].ok)
        self.assertEqual(results[0].error, "schema")
        self.assertEqual(server.chat_calls, 2)

    def test_prefix_sorted_submission(self):
        server = StubServer()
        reqs = [req(i, prefix=f"prefix {i % 4}") for i in range(20)]
        run(with_gateway(server, {"hero": backend(limit=1)}, lambda gw: gw.generate_many(reqs)))
        prefixes = [p.split("\n\n")[0] for p in server.prompts]
        runs = [prefixes[0]] + [b for a, b in zip(prefixes, prefixes[1:]) if a != b]
        self.assertEqual(len(runs), 4)   # each prefix sent as one contiguous group

    def test_embed_many_batches_and_dedupes(self):
        server = StubServer()
        texts = [f"memory {i % 100}" for i in range(150)]
        vectors = run(with_gateway(server, {"hero": backend()}, lambda gw: gw.embed_many(texts)))
        self.assertEqual(len(vectors), 150)
        self.assertEqual(vectors[0], vectors[100])
        self.assertEqual(server.embedded_texts, 100)
        self.assertEqual(server.embed_calls, math.ceil(100 / 64))

    def test_aimd_limiter(self):
        lim = AIMDLimiter(8)
        lim.on_backpressure()
        lim.on_backpressure()
        self.assertEqual(lim.limit, 2.0)
        for _ in range(200):
            lim.on_success()
        self.assertEqual(lim.limit, 8.0)
        for _ in range(10):
            lim.on_backpressure()
        self.assertEqual(lim.limit, 1.0)

    def test_parse_json_variants(self):
        self.assertEqual(parse_json('```json\n{"mood": "calm", "count": 1}\n```', SCHEMA)[0]["mood"], "calm")
        self.assertEqual(parse_json('Sure: {"mood": "calm", "count": 1} ok', SCHEMA)[0]["count"], 1)
        self.assertIsNotNone(parse_json('{"mood": "calm"}', SCHEMA)[1])
        self.assertIsNotNone(parse_json('{"mood": "calm", "count": true}', SCHEMA)[1])
        self.assertIsNotNone(parse_json(json.dumps([1]), SCHEMA)[1])


if __name__ == "__main__":
    unittest.main()
