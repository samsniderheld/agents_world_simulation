"""Dice & DM core (agents/dm/): dice, checks, contests, sheets, effects, stats."""

import collections
import random
import shutil
import statistics
import tempfile
import unittest
from pathlib import Path

from agents.dm import effects, rules, stats
from agents.dm.sheet import CharacterSheet, attitude_label


def sheet(**stats_):
    base = {s: 10 for s in rules.STATS}
    base.update(stats_)
    return CharacterSheet(stats=base, money=20)


class Dice(unittest.TestCase):
    def test_modifiers(self):
        self.assertEqual([rules.modifier(s) for s in (3, 8, 9, 10, 11, 14, 18, 20)], [-4, -1, -1, 0, 0, 2, 4, 5])

    def test_odds_and_crits(self):
        rng = random.Random(1)
        counts = collections.Counter(rules.check(14, "DEX", 15, rng).outcome for _ in range(40000))
        # +2 vs 15 needs 13+ on the die: 8/20 succeed, nat 1 and nat 20 are 1/20 each
        self.assertAlmostEqual((counts["success"] + counts["crit_success"]) / 40000, 0.40, delta=0.01)
        self.assertAlmostEqual(counts["crit_success"] / 40000, 0.05, delta=0.005)
        self.assertAlmostEqual(counts["crit_failure"] / 40000, 0.05, delta=0.005)

    def test_nat_20_and_nat_1_ignore_the_dc(self):
        rng = random.Random(0)
        results = [rules.check(3, "STR", 30, rng) for _ in range(3000)]
        self.assertTrue(all(r.outcome == "crit_success" for r in results if r.roll == 20))
        results = [rules.check(20, "STR", 2, rng) for _ in range(3000)]
        self.assertTrue(all(r.outcome == "crit_failure" for r in results if r.roll == 1))

    def test_advantage(self):
        rng = random.Random(2)
        adv = statistics.mean(rules.check(10, "DEX", 10, rng, advantage=1).roll for _ in range(20000))
        dis = statistics.mean(rules.check(10, "DEX", 10, rng, advantage=-1).roll for _ in range(20000))
        self.assertAlmostEqual(adv, 13.82, delta=0.15)
        self.assertAlmostEqual(dis, 7.18, delta=0.15)
        self.assertIn("(adv)", rules.check(10, "DEX", 10, rng, advantage=1).label())

    def test_opposed_ties_go_to_the_defender(self):
        rng = random.Random(4)
        for _ in range(3000):
            a, b, a_won = rules.opposed(10, "CHA", 10, "WIS", rng)
            if a.outcome.startswith("crit"):
                continue
            self.assertEqual(a_won, a.total > b.total)
            self.assertEqual(a.success, a_won)

    def test_difficulty_and_stat_names(self):
        self.assertEqual(rules.difficulty_dc("Hard"), 20)
        self.assertEqual(rules.difficulty_dc("nonsense"), 15)
        self.assertEqual(rules.normalise_stat("dexterity"), "DEX")
        self.assertEqual(rules.normalise_stat("luck"), "WIS")


class Sheets(unittest.TestCase):
    def test_conditions_give_advantage_and_wear_off(self):
        s = sheet()
        s.add_condition("drunk")
        self.assertEqual((s.advantage("CHA"), s.advantage("DEX"), s.advantage("STR")), (1, -1, 0))
        for _ in range(3):
            s.end_tick()
        self.assertEqual(s.conditions, {})

    def test_mood_drifts_back(self):
        s = sheet()
        s.shift_mood(3, "triumphant")
        self.assertEqual(s.mood_text(), "elated (triumphant)")
        s.end_tick()                     # the tick it happened: no drift yet
        self.assertEqual(s.mood, 3)
        for _ in range(3):
            s.end_tick()
        self.assertEqual(s.mood_text(), "steady")
        self.assertNotIn("stirred", s.to_dict())

    def test_summary_and_round_trip(self):
        s = sheet()
        s.set_goals(["pay off Sal", "find the ledger"])
        s.shift_attitude("Marsh", -30)
        s.add_condition("injured")
        text = s.summary("dollars", others=["Marsh", "Vera"])
        for part in ("Mood: steady", "injured", "20 dollars", "pay off Sal (0/3)", "unfriendly toward Marsh"):
            self.assertIn(part, text)
        self.assertNotIn("Vera", text)
        self.assertEqual(CharacterSheet.from_dict(s.to_dict()), s)
        self.assertEqual([attitude_label(v) for v in (-80, -30, -10, 0, 20, 60)],
                         ["hostile", "unfriendly", "wary", "neutral", "friendly", "loyal"])


class Effects(unittest.TestCase):
    def result(self, outcome, stat="DEX"):
        return rules.CheckResult(stat, [10], 10, 0, 0, 10, 15, outcome)

    def test_goal_progress_and_crits(self):
        s = sheet()
        s.set_goals(["crack the safe"])
        effects.apply_check(s, self.result("success"), goal_index=0)
        notes = effects.apply_check(s, self.result("crit_success"), goal_index=0)
        self.assertEqual(s.goals[0]["status"], "achieved")
        self.assertIn("inspired", notes)
        s.set_goals(["climb the fire escape"])
        notes = effects.apply_check(s, self.result("crit_failure", "DEX"), goal_index=0)
        self.assertIn("injured", notes)
        self.assertEqual(s.goals[0]["progress"], 0)

    def test_narrated_effects_are_clamped(self):
        s = sheet()
        effects.apply_narrated(s, {"money": -500, "condition": "drunk"})
        self.assertEqual(s.money, 0)                       # never below zero
        self.assertIn("drunk", s.conditions)
        effects.apply_narrated(s, {"money": 10_000, "condition": "immortal"})
        self.assertEqual(effects.apply_narrated(sheet(), {"condition": "drunk"}, critical=False), [])
        self.assertEqual(s.money, effects.MONEY_LIMIT)
        self.assertNotIn("immortal", s.conditions)
        self.assertEqual(effects.apply_narrated(s, "nonsense"), [])

    def test_social(self):
        lou, vera = sheet(), sheet()
        effects.apply_social(lou, vera, "Lou", "Vera", "charm", True)
        self.assertGreater(vera.attitude("Lou"), 0)
        effects.apply_social(lou, vera, "Lou", "Vera", "deceive", False)
        self.assertLess(vera.attitude("Lou"), 0)
        effects.apply_social(lou, vera, "Lou", "Vera", "threaten", True)
        self.assertLess(vera.mood, 0)


class Stats(unittest.TestCase):
    def test_deterministic_and_archetyped(self):
        a = stats.roll_for("longshoreman", "", "bg_00001")
        self.assertEqual(a, stats.roll_for("longshoreman", "", "bg_00001"))
        self.assertEqual(max(a.stats, key=a.stats.get), "STR")
        boss = stats.roll_for("mob boss", "", "char_x")
        self.assertEqual(max(boss.stats, key=boss.stats.get), "CHA")
        self.assertTrue(all(3 <= v <= 18 for v in a.stats.values()))

    def test_saved_sheet_wins(self):
        saved = sheet(STR=18).to_dict()
        self.assertEqual(stats.sheet_from_record({"id": "c", "sheet": saved}).stats["STR"], 18)


class SheetPersistence(unittest.TestCase):
    def setUp(self):
        from citystate import store
        self.store = store
        self.tmp = Path(tempfile.mkdtemp(prefix="dmtest_"))
        self.saved = (store._CITIES_DIR, store._ACTIVE_FILE, store._cache, store._loaded, store._active_id)
        store._CITIES_DIR, store._ACTIVE_FILE = self.tmp / "cities", self.tmp / "active_city"
        (self.tmp / "cities" / "city_t").mkdir(parents=True)
        (self.tmp / "cities" / "city_t" / "city.json").write_text("{}")
        store._ACTIVE_FILE.write_text("city_t")
        store._cache, store._loaded, store._active_id = None, False, None
        store.add_character({"id": "char_t", "name": "Lou", "occupation": "private eye", "bio": "tired"})

    def tearDown(self):
        s = self.store
        s._CITIES_DIR, s._ACTIVE_FILE, s._cache, s._loaded, s._active_id = self.saved
        shutil.rmtree(self.tmp)

    def test_update_character_fields(self):
        s = stats.sheet_from_record(self.store.get()["characters"][0])
        s.shift_mood(2, "triumphant")
        self.store.update_character_fields("char_t", sheet=s.to_dict())
        self.assertEqual(self.store.get_agent("char_t")["sheet"]["mood"], 2)
        self.store._loaded = False                                   # reload from disk
        self.assertEqual(self.store.get()["characters"][0]["sheet"]["mood_word"], "triumphant")


class ParseReact(unittest.TestCase):
    def test_tags(self):
        from agents.dm.scene import parse_react
        self.assertEqual(parse_react("TALK persuade: persuade, I hear you know things"),
                         ("talk", "persuade", "I hear you know things"))
        self.assertEqual(parse_react("**TALK (ask for help):** the money"), ("talk", "ask for help", "the money"))
        self.assertEqual(parse_react("TALK: the job"), ("talk", "persuade", "the job"))
        self.assertEqual(parse_react("REACT: leaves"), ("react", None, "leaves"))
        self.assertEqual(parse_react("whatever"), ("continue", None, ""))


if __name__ == "__main__":
    unittest.main()
