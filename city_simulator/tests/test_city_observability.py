"""CITY observability: the ring-buffered LOD recorder, cursor + filters on
/api/agents/events, and the per-tick metrics -- while SCENE's /events
keeps its old shape."""

import collections
import unittest
from unittest import mock

from agents.city import config as ccfg
from agents.city import recorder
from tests.city_fixtures import run_city


class RecorderTests(unittest.TestCase):
    def test_ring_buffer_and_dropped(self):
        with mock.patch.object(ccfg, "EVENT_BUFFER_SIZE", 50):
            recorder.start([{"name": "Lou"}], {})
            for i in range(120):
                recorder.log("action", i, agent="Lou", tier="hero", text=str(i))
        page = recorder.query(0, limit=None)
        self.assertEqual(len(page["events"]), 50)
        self.assertEqual(page["dropped"], 70)
        self.assertEqual(page["events"][0]["seq"], 71)
        self.assertEqual(page["next"], 120)
        self.assertEqual(recorder.query(120)["events"], [])
        # the hero's own full record isn't truncated by the live buffer
        self.assertEqual(len(recorder.hero_events()["Lou"]), 120)

    def test_paging_reads_everything_once(self):
        recorder.start([{"name": "Lou"}], {})
        for i in range(37):
            recorder.log("action" if i % 3 else "move", i, agent="Lou" if i % 2 else "Bo",
                         tier="hero" if i % 2 else "background", location="Pier 9" if i % 5 == 0 else "Ozzy's")
        for kwargs, expect in (({"tier": "all"}, 37), ({"tier": "hero"}, 18), ({"tier": "background"}, 19),
                               ({"tier": "all", "kinds": {"move"}}, 13), ({"tier": "all", "agent": "Bo"}, 19),
                               ({"tier": "all", "place": "Pier 9"}, 8)):
            seen, cursor = [], 0
            for _ in range(50):
                page = recorder.query(cursor, limit=4, **kwargs)
                seen += [e["seq"] for e in page["events"]]
                if page["next"] == cursor:
                    break
                cursor = page["next"]
            self.assertEqual(len(seen), expect, kwargs)
            self.assertEqual(len(seen), len(set(seen)), kwargs)

    def test_embeddings_stay_out_of_the_live_log(self):
        recorder.start([{"name": "Lou"}], {})
        recorder.log("memory", 0, agent="Lou", tier="hero", text="x", embedding=[0.1] * 768)
        self.assertNotIn("embedding", recorder.query(0)["events"][0])
        self.assertIn("embedding", recorder.hero_events()["Lou"][0])


class LevelOfDetailTests(unittest.TestCase):
    def test_background_events_are_coarse(self):
        world, _ = run_city(ticks=4, background_count=80)
        events = recorder.query(0, tier="all", limit=None)["events"]
        background_kinds = {e["kind"] for e in events if e["tier"] == "background"}
        self.assertTrue(background_kinds <= {"move", "encounter", "promotion", "schedules", "moves"}, background_kinds)
        per_tick = collections.Counter(e["tick"] for e in events if e["kind"] == "tick_summary")
        self.assertEqual(dict(per_tick), {0: 1, 1: 1, 2: 1, 3: 1})
        summary = next(e for e in events if e["kind"] == "tick_summary")
        self.assertTrue(summary["occupancy"])
        self.assertEqual(sum(o["heroes"] + o["background"] for o in summary["occupancy"]) + summary["off_map"],
                         len(world.heroes) + len(world.background))
        # no hero-only kinds for background agents
        names = {b.name for b in world.background}
        self.assertFalse({e["kind"] for e in events if e.get("agent") in names} & {"plan", "decompose", "memory", "focal"})

    def test_metrics_every_tick(self):
        world, _ = run_city(ticks=3, background_count=40)
        metrics = [e for e in recorder.query(0, limit=None)["events"] if e["kind"] == "metrics"]
        self.assertEqual(len(metrics), 3)
        for m in metrics:
            for key in ("seconds", "waves", "requests", "tokens_in", "tokens_out", "retries", "failures",
                        "tokens_per_second", "calls_per_hero", "calls_per_background"):
                self.assertIn(key, m)
            self.assertEqual(set(m["waves"]), {"plan", "decompose", "encounters", "react", "dialogue", "memory",
                                               "reflect", "promote"})
        self.assertEqual(recorder.state()["metrics"]["seq"], metrics[-1]["seq"])


class RouteTests(unittest.TestCase):
    def _client(self):
        from flask import Flask
        from agents import routes
        app = Flask(__name__)
        app.register_blueprint(routes.bp)
        return app.test_client()

    def test_scene_events_unchanged(self):
        from agents import jobs, recorder as scene_recorder
        scene_recorder.start([{"name": "Lou"}], {"mode": "scene"})
        for i in range(3):
            scene_recorder.log("action", i, agent="Lou", text="x")
        with mock.patch.object(jobs, "_mode", "scene"):
            body = self._client().get("/api/agents/events?since=1").get_json()
        self.assertEqual(set(body), {"events", "next"})
        self.assertEqual(body["next"], 3)
        self.assertEqual(len(body["events"]), 2)
        self.assertNotIn("seq", body["events"][0])

    def test_city_events_with_filters(self):
        from agents import jobs
        run_city(ticks=2, background_count=40)
        with mock.patch.object(jobs, "_mode", "city"):
            c = self._client()
            heroes_only = c.get("/api/agents/events?since=0&limit=5000").get_json()
            everything = c.get("/api/agents/events?since=0&tier=all&limit=5000").get_json()
            dialogue = c.get("/api/agents/events?since=0&kinds=dialogue,action&limit=5000").get_json()
            state = c.get("/api/agents/state").get_json()
        self.assertTrue(all(e["tier"] != "background" for e in heroes_only["events"]))
        self.assertGreater(len(everything["events"]), len(heroes_only["events"]))
        self.assertTrue(all(e["kind"] in ("dialogue", "action") for e in dialogue["events"]))
        self.assertEqual(heroes_only["next"], everything["next"])
        self.assertEqual(state["meta"]["mode"], "city")
        self.assertEqual(state["status"]["mode"], "city")
        self.assertIsNotNone(state["metrics"])


if __name__ == "__main__":
    unittest.main()
