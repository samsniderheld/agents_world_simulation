"""Dice & DM in a SCENE run (agents/dm/scene.py): seeded and reproducible,
tasks are rolled and narrated, social moves are contested, sheets change.
(The DM-off path is pinned by test_scene_regression.)"""

import collections
import json
import os
import unittest
from pathlib import Path

from agents import recorder
from tests.test_scene_regression import run_scenario

GOLDEN = Path(__file__).parent / "golden" / "scene_dm.json"
PARAMS = dict(ticks=6, tick_minutes=60, start_time="18:00", directive="they are circling a missing shipment",
              dm=True, seed=7)


class SceneDMTests(unittest.TestCase):
    maxDiff = None

    def test_golden_and_deterministic(self):
        got = run_scenario(PARAMS)
        if os.environ.get("UPDATE_GOLDEN"):
            GOLDEN.write_text(json.dumps(got, indent=1) + "\n")
        self.assertEqual(json.loads(GOLDEN.read_text()), got)
        self.assertEqual(run_scenario(PARAMS), got)

    def test_checks_outcomes_and_sheets(self):
        run_scenario(PARAMS)
        events = recorder.to_dict()["events"]
        kinds = collections.Counter(e["kind"] for e in events)
        self.assertGreater(kinds["check"], 0)
        self.assertGreater(kinds["outcome"], 0)
        checks = [e for e in events if e["kind"] == "check"]
        self.assertTrue(all(1 <= e["roll"] <= 20 for e in checks))
        plain = [e for e in checks if not e.get("opposed_by")]
        self.assertTrue(all(e["outcome"] == ("crit_success" if e["roll"] == 20 else "crit_failure" if e["roll"] == 1
                                             else "success" if e["total"] >= e["dc"] else "failure") for e in plain))
        outcomes = {e["outcome"] for e in checks}
        self.assertTrue({"success", "failure"} & outcomes)
        social = [e for e in checks if e.get("opposed_by")]
        self.assertTrue(social, "no social contests happened")
        memories = [e["text"] for e in events if e["kind"] == "memory"]
        self.assertTrue(any(" tried to " in m and " vs " in m for m in memories))
        self.assertEqual(recorder.get_meta()["dm"], True)

    def test_trivial_tasks_are_not_rolled(self):
        run_scenario(PARAMS)
        events = recorder.to_dict()["events"]
        decomposed = [(e["agent"], t) for e in events if e["kind"] == "decompose" for t in e.get("tasks", [])]
        rolled_actions = {(e["agent"], e["action"]) for e in events if e["kind"] == "check" and not e.get("opposed_by")}
        trivial = {(agent, t["action"]) for agent, t in decomposed if t["difficulty"] == "trivial"}
        self.assertTrue(trivial)
        self.assertFalse(trivial & rolled_actions)


if __name__ == "__main__":
    unittest.main()
