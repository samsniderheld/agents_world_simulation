"""CITY world loop (agents/city/world.py) against the stub server."""

import collections
import random
import unittest

from agents.city import population as pop
from agents.city import prompts, recorder
from agents.city.stub_server import StubServer
from agents.city.tiers import BackgroundAgent, CityHero, validate_schedule
from agents.city.world import CityWorld
from tests.city_fixtures import START, arun, fake_city, run_city, stub_gateway


def crowd(n_heroes: int, n_background: int, places: list):
    heroes = [CityHero(f"Hero {i}", 40, "a regular", "busy", places[i % len(places)]) for i in range(n_heroes)]
    background = []
    for i in range(n_background):
        b = BackgroundAgent({"id": f"bg_{i:05d}", "name": f"Resident {i}", "age": 30, "occupation": "clerk",
                             "bio": "A clerk.", "work": None, "haunt": None, "home": None})
        b.location = places[i % len(places)]
        background.append(b)
    return heroes, background


class EncounterTests(unittest.TestCase):
    def _world(self, heroes, background, cap=3):
        world = CityWorld(None, heroes, background, fake_city(), start=START, tick_minutes=30,
                          max_encounters_per_place=cap)
        recorder.start([{"name": h.name} for h in heroes], {})
        world._index_places()
        return world

    def test_no_agent_in_two_encounters_and_cap_per_place(self):
        places = ["Ozzy's Bar", "Pier 9", "St. Agnes"]
        heroes, background = crowd(7, 300, places)
        world = self._world(heroes, background, cap=5)
        for tick in range(5):
            world.tick = tick
            world._index_places()
            hero_pairs = world._encounters()
            events = [e for e in recorder.snapshot(0, tier="all")[0] if e["kind"] == "encounter" and e["tick"] == tick]
            seen = collections.Counter()
            per_place = collections.Counter()
            for e in events:
                seen[e["agent"]] += 1
                seen[e["other"]] += 1
                per_place[e["place"]] += 1
            self.assertTrue(all(v == 1 for v in seen.values()), "an agent was in two encounters")
            self.assertTrue(all(v <= 5 for v in per_place.values()))
            self.assertEqual(len(hero_pairs), sum(1 for e in events if e["tier"] == "hero"))

    def test_heroes_pair_first(self):
        heroes, background = crowd(2, 50, ["Ozzy's Bar"])
        world = self._world(heroes, background, cap=1)
        pairs = world._encounters()
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0][0].tier, pairs[0][1].tier}, {"hero"})

    def test_private_locations_never_meet(self):
        heroes, background = crowd(0, 20, ["Ozzy's Bar"])
        for b in background:
            b.location = "home"
        world = self._world(heroes, background)
        self.assertEqual(world._encounters(), [])

    def test_matching_is_linear_not_quadratic(self):
        heroes, background = crowd(10, 5000, ["Ozzy's Bar"])
        world = self._world(heroes, background, cap=3)
        import time
        t = time.monotonic()
        world._encounters()
        self.assertLess(time.monotonic() - t, 0.5)


class DialogueTests(unittest.TestCase):
    def test_lockstep_batches(self):
        """Every conversation advances one line per batch: the dialogue wave
        makes at most MAX_DIALOGUE_TURNS generate_many calls, the first one
        carrying every conversation."""
        server = StubServer(reply_fn=lambda p, s: "Keep your voice down, pal.")
        heroes, background = crowd(4, 4, ["Ozzy's Bar", "Pier 9"])

        async def go():
            async with stub_gateway(server) as gw:
                world = CityWorld(gw, heroes, background, fake_city(), start=START, tick_minutes=30)
                recorder.start([{"name": h.name} for h in heroes], {})
                world._index_places()
                from agents.city.world import _Conversation
                convs = [_Conversation(heroes[i], background[i], "Ozzy's Bar", "the job") for i in range(4)]
                sizes = []
                original = gw.generate_many

                async def spy(reqs):
                    sizes.append(len(reqs))
                    return await original(reqs)
                gw.generate_many = spy
                await world._dialogue_wave(convs)
                return convs, sizes
        convs, sizes = arun(go())
        self.assertEqual(sizes, [4] * 6)
        self.assertTrue(all(len(c.lines) == 6 for c in convs))
        self.assertTrue(all(c.lines[0].startswith(c.a.name) and c.lines[1].startswith(c.b.name) for c in convs))
        self.assertTrue(all(b.hero_interactions == 1 for b in background))

    def test_end_marker_stops_one_conversation_only(self):
        def replier(prompt, schema):
            return "[END]" if "Hero 0" in prompt.split("\n\n")[2] else "Not now."
        server = StubServer(reply_fn=replier)
        heroes, background = crowd(2, 2, ["Ozzy's Bar"])

        async def go():
            async with stub_gateway(server) as gw:
                world = CityWorld(gw, heroes, background, fake_city(), start=START, tick_minutes=30)
                recorder.start([{"name": h.name} for h in heroes], {})
                world._index_places()
                from agents.city.world import _Conversation
                convs = [_Conversation(heroes[0], background[0], "Ozzy's Bar", ""),
                         _Conversation(heroes[1], background[1], "Ozzy's Bar", "")]
                await world._dialogue_wave(convs)
                return convs
        convs = arun(go())
        self.assertEqual(convs[0].lines, [])
        self.assertEqual(len(convs[1].lines), 6)


class ParserTests(unittest.TestCase):
    def test_parse_react(self):
        self.assertEqual(prompts.parse_react("TALK: the missing crate"), ("talk", "the missing crate"))
        self.assertEqual(prompts.parse_react("Sure.\nREACT: leaves by the back door"), ("react", "leaves by the back door"))
        self.assertEqual(prompts.parse_react("**CONTINUE**"), ("continue", ""))
        self.assertEqual(prompts.parse_react("TALK:"), ("continue", ""))
        self.assertEqual(prompts.parse_react("I think they should talk"), ("continue", ""))

    def test_parse_line(self):
        self.assertEqual(prompts.parse_line('Lou: "Where were you?" (leaning in)', "Lou Marino"), "Where were you?")
        self.assertIsNone(prompts.parse_line("[END]", "Lou Marino"))
        self.assertEqual(prompts.parse_line("Not tonight, Vera.", "Lou Marino"), "Not tonight, Vera.")


class ScheduleTests(unittest.TestCase):
    PLACES = {"Ozzy's Bar", "Pier 9", "home", "elsewhere"}

    def test_validate_drops_bad_blocks(self):
        raw = [{"start": "00:00", "end": "07:00", "activity": "sleep", "place": "home"},
               {"start": "07:00", "end": "12:00", "activity": "work", "place": "Pier 9"},
               {"start": "12:00", "end": "13:00", "activity": "lunch", "place": "The Moon"},
               {"start": "25:00", "end": "26:00", "activity": "?", "place": "home"},
               {"start": "18:00", "end": "00:00", "activity": "drinks", "place": "ozzy's bar"}]
        blocks = validate_schedule(raw, self.PLACES)
        self.assertEqual([(b.place, b.start, b.end) for b in blocks],
                         [("home", 0, 420), ("Pier 9", 420, 720), ("Ozzy's Bar", 1080, 1440)])

    def test_validate_rejects_useless(self):
        self.assertEqual(validate_schedule([{"start": "x"}], self.PLACES), [])
        self.assertEqual(validate_schedule("nope", self.PLACES), [])

    def test_templates_cover_the_day(self):
        city = fake_city()
        for r in pop.generate(city, 50, seed=7):
            b = BackgroundAgent(r)
            blocks = pop.template_schedule(b, random.Random(1))
            self.assertEqual(blocks[0].start, 0)
            self.assertEqual(blocks[-1].end, 1440)
            for x, y in zip(blocks, blocks[1:]):
                self.assertEqual(x.end, y.start)
            places = set(pop.schedule_places(city))
            self.assertTrue(all(blk.place in places for blk in blocks))


class WorldRunTests(unittest.TestCase):
    def test_full_run_and_determinism(self):
        def events():
            run_city(ticks=3, background_count=40)
            return [(e["kind"], e["agent"], e["tick"]) for e in recorder.snapshot(0, tier="all")[0] if e["kind"] != "metrics"]
        first, second = events(), events()
        self.assertEqual(first, second)
        kinds = collections.Counter(k for k, _, _ in first)
        for kind in ("plan", "decompose", "action", "memory", "encounter"):
            self.assertGreater(kinds[kind], 0, kind)

    def test_background_llm_calls_per_tick_are_low(self):
        world, server = run_city(ticks=6, background_count=150, tick_minutes=30)
        per_bg = [m["calls_per_background"] for m in world.metrics_history]
        self.assertLess(sum(per_bg) / len(per_bg), 0.2)

    def test_failures_do_not_stop_the_run(self):
        from agents.city import config as ccfg
        saved, ccfg.BACKOFF_BASE_SECONDS = ccfg.BACKOFF_BASE_SECONDS, 0.001
        try:
            server = StubServer(reply_fn=prompts.stub_reply, failure_rate=0.3, seed=5)
            world, _ = run_city(server, ticks=3, background_count=30)
        finally:
            ccfg.BACKOFF_BASE_SECONDS = saved
        self.assertEqual(world.tick, 3)
        self.assertGreater(server.failures_served, 0)

    def test_template_only_background_makes_no_background_calls(self):
        world, _ = run_city(ticks=3, background_count=60, llm_schedules=False)
        self.assertTrue(all(m["calls_by_tier"].get("background", 0) == 0 or m["conversations"]
                            for m in world.metrics_history))
        self.assertEqual(sum(m["calls_by_kind"].get("schedule", 0) for m in world.metrics_history), 0)

    def test_llm_schedule_cap(self):
        world, _ = run_city(ticks=1, background_count=120)          # mac profile: 40 a day
        self.assertEqual(world.metrics_history[0]["calls_by_kind"].get("schedule"), 40)
        sources = collections.Counter(b.schedule_source for b in world.background)
        self.assertEqual(sources, {"llm": 40, "template": 80})

    def test_convene_anchors_heroes(self):
        world, _ = run_city(ticks=3, convene_at="St. Agnes")
        self.assertTrue(all(h.location == "St. Agnes" for h in world.heroes))

    def test_stop_flag(self):
        import threading
        stop = threading.Event()
        stop.set()
        world, _ = run_city(ticks=5, stop_flag=stop)
        self.assertEqual(world.tick, 0)


if __name__ == "__main__":
    unittest.main()
