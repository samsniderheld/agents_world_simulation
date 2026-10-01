"""Continuity between CITY and SCENE: heroes' memories persist in the same
shape, zooming into a place/time yields the right SCENE cast, place and
start time (promoting background residents on the way), and treatments
branch on the run's mode."""

import contextlib
import io
import json
import unittest
from unittest import mock

from agents import config, providers, recorder as scene_recorder, simulation, treatment, world as scene_world
from agents.city import prompts, zoom
from agents.city.stub_server import StubServer
from agents.memory import MemoryStream
from tests.city_fixtures import FakeStorage, fake_storage, run_city
from tests.scene_stub import SerialExecutor, StubProvider


def records_from(storage) -> dict:
    """What citystate would hold per hero after append_agent_run."""
    records = {}
    for run_record, slices in storage.appended:
        for agent in run_record["agents"]:
            records.setdefault(agent["name"], {"runs": []})["runs"].append(
                {"started_at": run_record["started_at"], "meta": run_record["meta"],
                 "events": (slices or {}).get(agent["name"], [])})
    return records


class PersistTests(unittest.TestCase):
    def test_heroes_persist_in_scene_shape(self):
        world, _ = run_city(ticks=4, background_count=40)
        self.assertTrue(all(r["meta"]["mode"] == "city" for r, _ in world.storage.appended))
        self.assertEqual({a["name"] for r, _ in world.storage.appended for a in r["agents"]},
                         {h.name for h in world.heroes if h.character_id})
        slices = {name: events for _, s in world.storage.appended for name, events in s.items()}
        for hero in world.heroes:
            if not hero.character_id:
                continue
            events = slices[hero.name]
            json.dumps(events)    # embeddings are plain lists by now
            memories = [e for e in events if e["kind"] == "memory"]
            self.assertTrue(memories)
            self.assertTrue(all(len(e["embedding"]) == 16 for e in memories))
            # SCENE's own rehydration reads it
            stream = MemoryStream.from_persisted({"runs": [{"events": events}]})
            self.assertEqual(len(stream.nodes), len(memories))
            # background lines said to this hero are part of their slice
            for e in events:
                if e["kind"] == "dialogue" and e["agent"] != hero.name:
                    self.assertEqual(e["listener"], hero.name)

    def test_toggle_off(self):
        world, _ = run_city(ticks=2, persist_hero_memories=False)
        self.assertEqual(world.storage.appended, [])
        self.assertEqual(len(world.storage.city_runs), 1)     # the compact summary is still saved

    def test_hydrates_next_city_run(self):
        storage = FakeStorage()
        run_city(ticks=2, storage=storage)
        for name, record in records_from(storage).items():
            char = next(c for c in storage.city["characters"] if c["name"] == name)
            storage.records[char["id"]] = record
        from agents.city.run import build_heroes
        with fake_storage(storage):
            heroes = build_heroes(storage.city)
        self.assertTrue(all(len(h.memory.nodes) > 0 for h in heroes))


class ZoomTests(unittest.TestCase):
    def setUp(self):
        self.server = StubServer(reply_fn=prompts.stub_reply)
        self.storage = FakeStorage()
        self.world, _ = run_city(self.server, ticks=4, background_count=60, storage=self.storage)
        self.ctx = fake_storage(self.storage)
        self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _busiest(self):
        opts = zoom.options()
        self.assertEqual(opts["ticks"], 4)
        self.assertEqual(opts["times"][:2], ["17:00", "18:00"])
        return max(opts["places"], key=lambda p: (p["heroes"], p["people"]))["name"]

    def test_zoom_promotes_background_and_returns_scene_params(self):
        place = self._busiest()
        summary = zoom._source()
        cast = zoom.cast_at(summary, place, 1, 2)
        result = zoom.zoom(place, 1, 2, transport=self.server.transport())
        self.assertEqual(result["agent_names"], [n for n, _, _ in cast])
        self.assertEqual(result["start_time"], "18:00")
        self.assertEqual((result["ticks"], result["tick_minutes"]), (2, 60))
        self.assertEqual(result["place_id"], next(p["id"] for p in self.storage.city["places"] if p["name"] == place))
        promoted = [n for n, is_hero, _ in cast if not is_hero]
        self.assertEqual(sorted(result["promoted"]), sorted(promoted))
        for c in self.storage.added:
            self.assertTrue(c["bio"])
            self.assertTrue(c["promoted_from"].startswith("bg_"))
            resident = next(r for r in self.storage.background if r["id"] == c["promoted_from"])
            self.assertEqual(resident["promoted_to"], c["id"])
        # heroes first in the cast
        flags = [is_hero for _, is_hero, _ in cast]
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_scene_run_starts_with_the_right_cast_place_and_time(self):
        place = self._busiest()
        result = zoom.zoom(place, 0, 1, transport=self.server.transport())

        class SceneCity:
            def __init__(self, city):
                self.city = city

            def get(self):
                return self.city

            def get_agent(self, _):
                return None

            def append_agent_run(self, run_record):
                pass

        stub = StubProvider()
        saved_instances = dict(providers._instances)
        saved = (config.PROVIDER, config.CHAT_MODEL, scene_world.ThreadPoolExecutor, simulation.citystate,
                 simulation._active_roster)
        providers._instances["ollama"] = stub
        scene_world.ThreadPoolExecutor = SerialExecutor
        simulation.citystate = SceneCity(self.storage.city)
        simulation.set_history_roster(self.storage.city)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                simulation.run(provider="ollama", agent_names=result["agent_names"], convene_at=result["place"],
                               start_time=result["start_time"], tick_minutes=result["tick_minutes"],
                               ticks=result["ticks"], directive=result["directive"])
        finally:
            providers._instances.clear()
            providers._instances.update(saved_instances)
            (config.PROVIDER, config.CHAT_MODEL, scene_world.ThreadPoolExecutor, simulation.citystate,
             simulation._active_roster) = saved
        agents = scene_recorder.get_agents()
        self.assertEqual([a["name"] for a in agents], result["agent_names"])
        self.assertTrue(all(a["location"] == place for a in agents))
        meta = scene_recorder.get_meta()
        self.assertEqual((meta["mode"], meta["start_time"], meta["ticks"]), ("scene", result["start_time"], result["ticks"]))
        actions = [e for e in scene_recorder.to_dict()["events"] if e["kind"] == "action"]
        import datetime
        self.assertEqual(actions[0]["time"], datetime.datetime.strptime(result["start_time"], "%H:%M").strftime("%I:%M %p"))
        self.assertTrue(all(e["location"] == place for e in actions))

    def test_nobody_there(self):
        with self.assertRaises(ValueError):
            zoom.zoom("Nowhere", 0, 1, transport=self.server.transport())

    def test_promoted_residents_are_not_background_next_run(self):
        place = self._busiest()
        result = zoom.zoom(place, 0, 3, transport=self.server.transport())
        if not result["promoted"]:
            self.skipTest("no background residents at the busiest place")
        world, _ = run_city(self.server, ticks=1, background_count=60, storage=self.storage,
                            city=self.storage.city)
        names = {b.name for b in world.background}
        self.assertFalse(names & set(result["promoted"]))
        self.assertTrue(set(result["promoted"]) <= {h.name for h in world.heroes})


class ZoomMemoryTests(unittest.TestCase):
    """Everyone a zoom turns into a character starts with memories of the
    CITY run -- even someone who met nobody, and someone who'd been promoted
    to hero mid-run."""

    def _memories(self, storage, name):
        cid = next(c["id"] for c in storage.city["characters"] if c["name"] == name)
        return [e["text"] for run in storage.records.get(cid, {}).get("runs", []) for e in run["events"]
                if e["kind"] == "memory"]

    def test_every_promoted_character_gets_memories(self):
        server = StubServer(reply_fn=prompts.stub_reply)
        storage = FakeStorage()

        def promote_one(world):
            world.promotion_requests.append(world.background[0].name)
        world, _ = run_city(server, ticks=4, background_count=40, storage=storage, on_world=promote_one)
        mid_run = next(h.name for h in world.heroes if h.promoted_from)
        summary = storage.city_runs[-1]
        self.assertTrue(summary["promoted_memories"][mid_run])
        with fake_storage(storage):
            for opt in zoom.options()["places"]:
                zoom.zoom(opt["name"], 0, 3, transport=server.transport())
        promoted = [c for c in storage.city["characters"] if c.get("promoted_from")]
        self.assertTrue(promoted)
        self.assertIn(mid_run, [c["name"] for c in promoted])
        for c in promoted:
            mems = self._memories(storage, c["name"])
            self.assertTrue(mems, c["name"])
            self.assertTrue(any(" was at " in m for m in mems), c["name"])        # where they were
        self.assertTrue(any("(" in m and ")." in m for c in promoted for m in self._memories(storage, c["name"])))

    def test_earlier_zoom_characters_are_backfilled_once(self):
        server = StubServer(reply_fn=prompts.stub_reply)
        storage = FakeStorage()
        run_city(server, ticks=3, background_count=40, storage=storage)
        with fake_storage(storage):
            place = zoom.options()["places"][0]["name"]
            first = zoom.zoom(place, 0, 2, transport=server.transport())
            if not first["promoted"]:
                self.skipTest("no background residents at the busiest place")
            name = first["promoted"][0]
            cid = next(c["id"] for c in storage.city["characters"] if c["name"] == name)
            storage.records.pop(cid)                   # as if saved before memories were kept
            zoom.zoom(place, 0, 2, transport=server.transport())
            zoom.zoom(place, 0, 2, transport=server.transport())
        self.assertEqual(len(storage.records[cid]["runs"]), 1)
        self.assertTrue(self._memories(storage, name))


class GalleryResidentsTests(unittest.TestCase):
    def test_list_and_make_character(self):
        server = StubServer(reply_fn=prompts.stub_reply)
        storage = FakeStorage()
        run_city(server, ticks=3, background_count=30, storage=storage)
        with fake_storage(storage):
            listed = zoom.residents()
            self.assertEqual(len(listed), 30)
            self.assertTrue(all(r["hero_interactions"] is not None for r in listed))
            target = max(listed, key=lambda r: r["hero_interactions"])
            made = zoom.make_character(target["id"], transport=server.transport())
            again = zoom.make_character(target["id"], transport=server.transport())
            after = {r["id"]: r for r in zoom.residents()}
        self.assertEqual(made["name"], target["name"])
        self.assertEqual(made["promoted_from"], target["id"])
        self.assertEqual(again["id"], made["id"])                          # not made twice
        self.assertEqual(after[target["id"]]["character_name"], target["name"])
        self.assertEqual(len([c for c in storage.added if c["name"] == target["name"]]), 1)

    def test_resident_detail(self):
        server = StubServer(reply_fn=prompts.stub_reply)
        storage = FakeStorage()
        run_city(server, ticks=4, background_count=30, tick_minutes=60, storage=storage)
        with fake_storage(storage):
            r = max(zoom.residents(), key=lambda x: x["hero_interactions"] or 0)
            d = zoom.resident_detail(r["id"])
            with self.assertRaises(ValueError):
                zoom.resident_detail("bg_nope")
        self.assertEqual(d["name"], r["name"])
        run = d["run"]
        self.assertTrue(run["in_run"])
        self.assertEqual(run["stays"][0]["from"], "17:00")
        self.assertEqual(run["stays"][-1]["until"], "21:00")
        self.assertTrue(all(s["place"] for s in run["stays"]))
        self.assertTrue(run["memories"])
        self.assertTrue(any(a["hero"] for a in run["acquaintances"]) or r["hero_interactions"] == 0)

    def test_without_any_city_run(self):
        server = StubServer(reply_fn=prompts.stub_reply)
        storage = FakeStorage()
        from agents.city import population as pop
        storage.background = pop.generate(storage.city, 5, seed=2)
        with fake_storage(storage):
            self.assertEqual([r["hero_interactions"] for r in zoom.residents()], [None] * 5)
            made = zoom.make_character(storage.background[0]["id"], transport=server.transport())
        self.assertTrue(made["bio"])
        self.assertEqual(storage.appended, [])          # no run to carry memories from
        with fake_storage(storage), self.assertRaises(ValueError):
            zoom.make_character("bg_nope", transport=server.transport())


class TreatmentTests(unittest.TestCase):
    def test_city_transcript_narrowed_by_place_and_ticks(self):
        world, _ = run_city(ticks=4, background_count=60)
        records = records_from(world.storage)
        started_at = world.storage.appended[0][0]["started_at"]
        full, names, places = treatment.build_city_transcript(records, started_at)
        self.assertTrue(full)
        place = places[0]
        narrow, narrow_names, narrow_places = treatment.build_city_transcript(records, started_at, place=place,
                                                                               tick_from=1, tick_to=2)
        self.assertEqual(narrow_places, [place] if narrow else [])
        self.assertLessEqual(len(narrow), len(full))
        self.assertTrue(set(narrow_names) <= set(names))
        capped, _, _ = treatment.build_city_transcript(records, started_at, max_lines=5)
        self.assertEqual(len(capped), min(5, len(full)))

    def test_route_branches_on_mode(self):
        from flask import Flask
        from agents import routes

        def fake_city(mode):
            run = {"started_at": "2026-01-01", "meta": {"mode": mode} if mode else {}, "events": []}
            record = {"id": "char_0", "name": "Lou", "runs": [run]}
            fake = mock.Mock()
            fake.get_agent.return_value = record
            fake.get.return_value = {"characters": [{"id": "char_0", "name": "Lou"}], "places": []}
            fake.get_background.return_value = []
            fake.add_treatment.return_value = {"text": "t"}
            return fake

        app = Flask(__name__)
        app.register_blueprint(routes.bp)
        for mode, expect_city in ((None, False), ("scene", False), ("city", True)):
            with mock.patch.object(routes, "citystate", fake_city(mode)), \
                    mock.patch.object(treatment, "generate_treatment", return_value="T"), \
                    mock.patch.object(treatment, "build_city_transcript", wraps=treatment.build_city_transcript) as city_spy, \
                    mock.patch.object(treatment, "build_transcript", wraps=treatment.build_transcript) as scene_spy:
                res = app.test_client().post("/api/agents/treatment", json={"agent_id": "char_0"})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(city_spy.called, expect_city, mode)
                self.assertEqual(scene_spy.called, not expect_city, mode)


if __name__ == "__main__":
    unittest.main()
