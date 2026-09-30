"""CITY tiers and population: the background generator, ring memory,
promotion, and the citystate storage for background residents and CITY
run summaries."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.city import population as pop
from agents.city import recorder
from agents.city.stub_server import StubServer
from agents.city.tiers import BackgroundAgent, RingMemory
from agents.city.world import CityWorld
from tests.city_fixtures import HEROES, START, FakeStorage, arun, fake_city, run_city, stub_gateway


class GeneratorTests(unittest.TestCase):
    def test_deterministic_and_prefix_stable(self):
        city = fake_city()
        small = pop.generate(city, 200, seed=11)
        big = pop.generate(city, 1000, seed=11)
        self.assertEqual(small, big[:200])
        self.assertEqual(big, pop.generate(city, 1000, seed=11))
        self.assertNotEqual(big, pop.generate(city, 1000, seed=12))

    def test_extending_matches_generating_at_once(self):
        city = fake_city()
        first = pop.generate(city, 300, seed=3)
        extended = pop.generate(city, 700, seed=3, start=300, existing=first)
        self.assertEqual(extended, pop.generate(city, 700, seed=3))

    def test_no_llm_calls(self):
        with mock.patch("history.llm.complete", side_effect=AssertionError("LLM called")), \
                mock.patch("agents.llm.complete", side_effect=AssertionError("LLM called")):
            residents = pop.generate(fake_city(), 1000, seed=1)
        self.assertEqual(len(residents), 1000)

    def test_unique_names_and_heroes_excluded(self):
        heroes = {n for n, _, _ in HEROES}
        residents = pop.generate(fake_city(), 1000, seed=5, taken_names=heroes)
        names = [r["name"] for r in residents]
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(heroes & set(names))

    def test_places_are_real(self):
        city = fake_city()
        active = {p["name"] for p in city["places"]}
        for r in pop.generate(city, 500, seed=2):
            for key in ("work", "haunt", "home"):
                self.assertTrue(r[key] is None or r[key] in active, (key, r[key]))
            self.assertTrue(r["bio"].startswith(r["name"]) or r["name"] in r["bio"])

    def test_city_with_no_places(self):
        residents = pop.generate({"places": []}, 20, seed=1)
        self.assertTrue(all(r["work"] is None and r["haunt"] is None for r in residents))


class RingMemoryTests(unittest.TestCase):
    def test_capacity_and_name_retrieval(self):
        mem = RingMemory(size=5)
        for i in range(8):
            mem.add(i, "encounter", f"Traded a few words with Person {i} about the weather.")
        self.assertEqual(len(mem.entries), 5)
        mem.add(9, "dialogue", "Talked with Lou Marino at Ozzy's Bar about the missing money.", with_hero=True)
        top = mem.retrieve("Lou Marino", k=1)
        self.assertIn("Lou Marino", top[0].text)
        self.assertGreater(top[0].importance, 5)


class PromotionTests(unittest.TestCase):
    def _world(self, gw, n_background=6, promote_after=3, hero_cap=10):
        from agents.city.tiers import CityHero
        heroes = [CityHero("Lou Marino", 45, "private eye", "busy", "Ozzy's Bar")]
        background = [BackgroundAgent(r) for r in pop.generate(fake_city(), n_background, seed=1)]
        for i, b in enumerate(background):
            b.location = "Ozzy's Bar"
            for k in range(3):
                b.memory.add(k, "encounter", f"{b.name} memory {k}")
        world = CityWorld(gw, heroes, background, fake_city(), start=START, tick_minutes=30,
                          promote_after=promote_after, hero_cap=hero_cap)
        recorder.start([{"name": "Lou Marino"}], {}, {"heroes": 1, "background": n_background})
        world._index_places()
        return world

    def test_threshold_promotion_converts_memory_in_one_batch(self):
        server = StubServer()

        async def go():
            async with stub_gateway(server) as gw:
                world = self._world(gw)
                world.background[0].hero_interactions = 3
                world.background[1].hero_interactions = 2
                target = world.background[0]
                await world._promote_wave()
                return world, target
        world, target = arun(go())
        names = [h.name for h in world.heroes]
        self.assertIn(target.name, names)
        self.assertNotIn(target.name, [b.name for b in world.background])
        hero = world.heroes[-1]
        self.assertEqual(len(hero.memory.nodes), 3)
        self.assertTrue(all(len(n.embedding) == 16 for n in hero.memory.nodes))
        self.assertEqual(server.embed_calls, 1)
        self.assertEqual(hero.promoted_from, target.id)
        self.assertEqual(recorder.state()["population"], {"heroes": 2, "background": 5})

    def test_ui_request_and_hero_cap(self):
        server = StubServer()

        async def go():
            async with stub_gateway(server) as gw:
                world = self._world(gw, hero_cap=2)
                world.promotion_requests.extend([world.background[4].name, world.background[5].name])
                await world._promote_wave()
                return world
        world = arun(go())
        self.assertEqual(len(world.heroes), 2)          # the cap: only the first request fits
        events = [e for e in recorder.snapshot(0)[0] if e["kind"] == "promotion"]
        self.assertEqual(len(events), 1)
        self.assertIn("picked in the UI", events[0]["text"])

    def test_promoted_hero_plans_and_acts_in_a_real_run(self):
        from agents.city import run as city_run

        def queue_first(world):
            world.promotion_requests.append(world.background[0].name)
        world, _ = run_city(ticks=3, background_count=30, on_world=queue_first)
        promoted = [h for h in world.heroes if h.promoted_from]
        self.assertGreaterEqual(len(promoted), 1)
        self.assertTrue(promoted[0].plan)
        acted = [e for e in recorder.snapshot(0)[0] if e["kind"] == "action" and e["agent"] == promoted[0].name]
        self.assertGreaterEqual(len(acted), 1)
        self.assertEqual(city_run.request_promotion(world.background[0].name), "no CITY run is in progress")


class RunSummaryTests(unittest.TestCase):
    def test_background_saved_and_reused(self):
        storage = FakeStorage()
        run_city(ticks=1, background_count=50, storage=storage)
        first = [r["name"] for r in storage.background]
        run_city(ticks=1, background_count=30, storage=storage)
        self.assertEqual([r["name"] for r in storage.background], first)   # not regenerated
        run_city(ticks=1, background_count=80, storage=storage)
        self.assertEqual([r["name"] for r in storage.background][:50], first)
        self.assertEqual(len(storage.background), 80)

    def test_summary_is_compact(self):
        world, _ = run_city(ticks=3, background_count=40)
        summary = world.storage.city_runs[-1]
        self.assertEqual(len(summary["positions"]), 3)
        self.assertEqual(len(summary["positions"][0]), len(summary["agents"]))
        self.assertTrue(all(-1 <= i < len(summary["places"]) for tick in summary["positions"] for i in tick))
        self.assertEqual(len(summary["background"]), len(world.background))
        self.assertNotIn("events", summary)
        self.assertTrue(all(not isinstance(v, list) or k in ("positions", "agents", "places", "heroes", "metrics")
                            for k, v in summary.items()))
        json.dumps(summary)   # serialisable


class CitystateStorageTests(unittest.TestCase):
    """The real citystate functions, pointed at a temporary directory."""

    def setUp(self):
        from citystate import store
        self.store = store
        self.tmp = Path(tempfile.mkdtemp(prefix="citytest_"))
        self.saved = (store._CITIES_DIR, store._ACTIVE_FILE, store._cache, store._loaded, store._active_id)
        store._CITIES_DIR = self.tmp / "cities"
        store._ACTIVE_FILE = self.tmp / "active_city"
        (self.tmp / "cities" / "city_test").mkdir(parents=True)
        (self.tmp / "cities" / "city_test" / "city.json").write_text("{}")
        store._ACTIVE_FILE.write_text("city_test")
        store._cache, store._loaded, store._active_id = None, False, None

    def tearDown(self):
        store = self.store
        store._CITIES_DIR, store._ACTIVE_FILE, store._cache, store._loaded, store._active_id = self.saved
        shutil.rmtree(self.tmp)

    def test_background_round_trip(self):
        residents = pop.generate(fake_city(), 100, seed=1)
        self.store.save_background(residents)
        self.assertEqual(self.store.get_background(), residents)
        raw = (self.tmp / "cities" / "city_test" / "background.json").read_text()
        self.assertNotIn("\n", raw)                    # compact
        self.assertTrue(self.store.update_background_resident(residents[3]["id"], promoted_to="char_x"))
        self.assertEqual(self.store.get_background()[3]["promoted_to"], "char_x")

    def test_city_runs(self):
        self.store.save_city_run({"started_at": "2026-01-01T10:00:00", "positions": [[0]], "heroes": [], "background": {}})
        self.store.save_city_run({"started_at": "2026-01-02T10:00:00", "positions": [[0], [1]], "heroes": [{}],
                                  "background": {"a": {}}})
        self.assertEqual(self.store.get_city_run()["started_at"], "2026-01-02T10:00:00")
        self.assertEqual(self.store.get_city_run("2026-01-01T10:00:00")["positions"], [[0]])
        self.assertEqual([r["ticks"] for r in self.store.list_city_runs()], [1, 2])


if __name__ == "__main__":
    unittest.main()
