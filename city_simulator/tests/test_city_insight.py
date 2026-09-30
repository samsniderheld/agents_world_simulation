"""City report / ask the city (agents/city/insight.py)."""

import unittest

from agents.city import insight, prompts, recorder
from agents.city.stub_server import StubServer
from tests.city_fixtures import FakeStorage, fake_storage, run_city


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.server = StubServer(reply_fn=lambda p, s: "STORYLINES: something is afoot." if "STORYLINES" in p
                                 else prompts.stub_reply(p, s))
        self.storage = FakeStorage()
        self.world, _ = run_city(self.server, ticks=4, background_count=40, storage=self.storage,
                                 directive="a payroll went missing")

    def _last_prompt(self):
        return self.server.prompts[-1]

    def test_report_from_live_run(self):
        with fake_storage(self.storage):
            res = insight.report(transport=self.server.transport())
        self.assertEqual(res["source"], "live")
        self.assertTrue(res["text"])
        prompt = self._last_prompt()
        self.assertIn("STORYLINES", prompt)
        self.assertIn("a payroll went missing", prompt)
        self.assertIn(" @ ", prompt)                       # action lines made it in
        self.assertNotIn("CHANGES", prompt)
        with fake_storage(self.storage):
            insight.report(previous="STORYLINES: old news.", transport=self.server.transport())
        self.assertIn("old news", self._last_prompt())
        self.assertIn("CHANGES", self._last_prompt())

    def test_ask_picks_relevant_lines(self):
        hero = self.world.heroes[0].name
        with fake_storage(self.storage):
            res = insight.ask(f"What has {hero.split()[0]} been up to?", transport=self.server.transport())
        self.assertTrue(res["text"])
        prompt = self._last_prompt()
        self.assertIn("Question: What has", prompt)
        self.assertIn(hero, prompt)

    def test_budget_is_respected(self):
        lines = [f"[tick {i}] Someone @ Somewhere: line number {i} " + "x" * 80 for i in range(2000)]
        kept = insight.recent_lines(lines, 5000)
        self.assertLessEqual(sum(len(x) + 1 for x in kept), 5000)
        self.assertEqual(kept[-1], lines[-1])
        rel = insight.relevant_lines(lines + ["[tick 9] Vera Katz @ Pier 9: hides the payroll"], "Where is the payroll? Ask Vera", 3000)
        self.assertIn("[tick 9] Vera Katz @ Pier 9: hides the payroll", rel)
        self.assertLessEqual(sum(len(x) + 1 for x in rel), 3000)

    def test_falls_back_to_the_saved_run(self):
        # FakeStorage already holds what citystate would after the run:
        # the heroes' records and the run summary.
        saved = recorder._started_at
        recorder._started_at = None                        # as after an app restart
        try:
            with fake_storage(self.storage):
                res = insight.report(transport=self.server.transport())
        finally:
            recorder._started_at = saved
        self.assertEqual(res["source"], "saved")
        self.assertGreater(res["lines_total"], 0)

    def test_errors(self):
        with fake_storage(FakeStorage()):
            saved = recorder._started_at
            recorder._started_at = None
            try:
                with self.assertRaises(ValueError):
                    insight.report(transport=self.server.transport())
            finally:
                recorder._started_at = saved
        with self.assertRaises(ValueError):
            insight.ask("  ", transport=self.server.transport())


if __name__ == "__main__":
    unittest.main()
