"""Dice & DM in CITY mode (agents/dm/city.py, agents/dm/background.py): a
seeded run against the stub server is reproducible (golden), heroes' tasks
are rolled and narrated, social checks shape the dialogue, background
residents roll with no LLM, and sheets are saved and picked up again.
With DM off, CITY is covered by tests/test_theme_golden.py (unchanged).

    UPDATE_GOLDEN=1 python -m unittest tests.test_dm_city    # re-record
"""

import collections
import hashlib
import json
import os
import random
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.city import recorder
from agents.dm import background as bg_dice
from agents.dm.sheet import CharacterSheet
from tests.city_fixtures import run_city

GOLDEN = Path(__file__).parent / "golden" / "city_dm.json"
PARAMS = dict(ticks=4, background_count=60, dm=True, seed=5, directive="a payroll went missing")


def _events():
    return [e for e in recorder.query(0, tier="all", limit=None)["events"] if e["kind"] not in ("metrics", "status")]


def snapshot(world, server) -> dict:
    events = _events()
    checks = [[e["tick"], e["agent"], e["text"]] for e in events if e["kind"] == "check"]
    return {"events": hashlib.sha256(json.dumps([[e["kind"], e.get("agent"), e["tick"], e.get("text")]
                                                 for e in events]).encode()).hexdigest()[:16],
            "prompts": hashlib.sha256("\n".join(server.prompts).encode()).hexdigest()[:16],
            "checks": checks,
            "counts": [m["checks"] for m in world.metrics_history]}


class CityDMRun(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.world, cls.server = run_city(**PARAMS)
        cls.events = _events()
        cls.got = snapshot(cls.world, cls.server)

    def test_golden_and_deterministic(self):
        if os.environ.get("UPDATE_GOLDEN"):
            GOLDEN.write_text(json.dumps(self.got, indent=1) + "\n")
        self.assertEqual(json.loads(GOLDEN.read_text()), self.got)
        again = snapshot(*run_city(**PARAMS))
        self.assertEqual(self.got, again)

    def test_heroes_roll_and_narrate(self):
        checks = [e for e in self.events if e["kind"] == "check" and e["tier"] == "hero" and "opposed_by" not in e]
        outcomes = [e for e in self.events if e["kind"] == "outcome" and e["tier"] == "hero"]
        self.assertTrue(checks)
        self.assertEqual(len(checks), len(outcomes))
        narrate = sum(m["calls_by_kind"].get("narrate", 0) for m in self.world.metrics_history)
        self.assertEqual(narrate, len(checks))      # one narration call per rolled task, nothing for trivial ones
        decompose = next(e for e in self.events if e["kind"] == "decompose")
        self.assertIn("stat", decompose["tasks"][0])

    def test_social_checks_reach_the_dialogue(self):
        social = [e for e in self.events if e["kind"] == "check" and "opposed_by" in e]
        self.assertTrue(social)
        self.assertTrue(any("The conversation must show this." in p for p in self.server.prompts))

    def test_background_rolls_without_llm(self):
        self.assertTrue(any(m["checks"]["background_checks"] for m in self.world.metrics_history))
        self.assertTrue(any(e["kind"] == "checks" for e in self.events))
        world, _ = run_city(**{**PARAMS, "llm_schedules": False, "ticks": 2})
        self.assertTrue(world.metrics_history[0]["checks"]["background_checks"])
        # the only background calls left: their lines in conversations with heroes
        self.assertEqual(sum(m["calls_by_tier"].get("background", 0) for m in world.metrics_history),
                         sum(m["calls_by_kind"].get("dialogue_bg", 0) for m in world.metrics_history))

    def test_sheets_saved_and_reloaded(self):
        storage = self.world.storage
        self.assertTrue(all(r.get("sheet") for r in storage.background[:60]))
        self.assertTrue(all(c.get("sheet") for c in storage.city["characters"]))
        lou = next(c for c in storage.city["characters"] if c["name"] == "Lou Marino")
        lou["sheet"]["money"] = 4321
        world, _ = run_city(**{**PARAMS, "ticks": 1, "storage": storage, "city": storage.city})
        self.assertGreater(next(h for h in world.heroes if h.name == "Lou Marino").sheet.money, 4000)

    def test_treatment_transcript_has_the_dice(self):
        from agents.treatment import build_city_transcript
        storage = self.world.storage
        started = storage.city_runs[0]["started_at"]
        log, names, _ = build_city_transcript(storage.records, started)
        dice = [ln for ln in log if " -- IT " in ln or " -- A TRIUMPH" in ln or " -- A DISASTER" in ln]
        self.assertTrue(dice)
        self.assertTrue(any(": It went as the dice said" in ln for ln in dice))     # a narrated task
        self.assertTrue(any(ln.split("] ", 1)[1].count(" -- ") == 1 and ":" not in ln.split(" -- ")[1]
                            for ln in dice))                                         # a social contest
        # narrowed to one place: only that place's dice results
        place = next(e["location"] for e in self.events if e["kind"] == "outcome" and e["tier"] == "hero")
        here = {e["text"] for e in self.events if e["kind"] == "outcome" and e.get("location") == place}
        narrowed, _, _ = build_city_transcript(storage.records, started, place=place)
        outcomes = [ln.rsplit(": ", 1)[1] for ln in narrowed if ": It went as the dice said" in ln]
        self.assertTrue(outcomes)
        self.assertTrue(set(outcomes) <= here)


class CityDMOff(unittest.TestCase):
    def test_no_dm_events_or_prompts(self):
        world, server = run_city(**{**PARAMS, "dm": False, "ticks": 2})
        self.assertFalse([e for e in _events() if e["kind"] in ("check", "outcome", "checks")])
        self.assertFalse(any("character sheet" in p for p in server.prompts))
        self.assertNotIn("checks", world.metrics_history[0])
        self.assertFalse(any(r.get("sheet") for r in world.storage.background))


class BackgroundDice(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(bg_dice.classify("working as a bartender")[0], "work")
        self.assertEqual(bg_dice.classify("asleep")[0], "rest")
        self.assertEqual(bg_dice.classify("getting ready for work")[0], "rest")
        self.assertEqual(bg_dice.classify("a drink after the shift")[0], "work")   # first kind with a match
        self.assertEqual(bg_dice.classify("feeding the pigeons")[0], "leisure")

    def test_roll_block(self):
        agent = SimpleNamespace(name="Pearl Rizzo", occupation="bartender", bio="")
        outcomes = collections.Counter()
        for i in range(400):
            sheet = CharacterSheet(stats={s: 12 for s in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}, money=50)
            out = bg_dice.roll_block(agent, sheet, "working as a bartender", "at Ozzy's Bar", random.Random(i))
            self.assertIsNotNone(out)          # work is never trivial
            outcomes[out["result"].outcome] += 1
            self.assertIn("Pearl Rizzo", out["text"])
            self.assertNotIn("{", out["text"])
            if out["result"].success:
                self.assertGreaterEqual(sheet.money, 50)
            self.assertGreaterEqual(sheet.money, 0)
        self.assertEqual(set(outcomes), {"crit_success", "success", "failure", "crit_failure"})
        sheet = CharacterSheet(stats={s: 10 for s in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}, money=50)
        self.assertIsNone(bg_dice.roll_block(agent, sheet, "asleep", "at home", random.Random(1)))


if __name__ == "__main__":
    unittest.main()
