"""SCENE-mode regression snapshot: 5 agents (the hardcoded noir cast), a
deterministic stub LLM, fixed settings. The recorder's event sequence
(kind, agent, tick, in order) and a digest of every prompt sent must match
the golden files exactly -- CITY mode is built alongside SCENE, and this is
what proves SCENE didn't move.

    python -m unittest tests.test_scene_regression           # check
    UPDATE_GOLDEN=1 python -m unittest tests.test_scene_regression   # re-record
"""

import contextlib
import hashlib
import io
import json
import os
import unittest
from pathlib import Path

from agents import config, providers, recorder, reflection, simulation, world
from agents.agent import Agent
from tests.scene_stub import SerialExecutor, StubCitystate, StubProvider, _h

GOLDEN = Path(__file__).parent / "golden"

SCENARIOS = {
    "grounded": dict(ticks=6, tick_minutes=30, start_time="06:00",
                     directive="they are circling a missing shipment"),
    "convened": dict(ticks=4, tick_minutes=60, start_time="21:00", convene_at="The Copper Fox"),
    # A low reflection threshold, so focal points and insights happen too.
    "reflective": dict(ticks=5, tick_minutes=120, start_time="08:00", _reflect_threshold=25),
}


def run_scenario(params: dict) -> dict:
    params = dict(params)
    threshold = params.pop("_reflect_threshold", None)
    saved_threshold = reflection.REFLECTION_IMPORTANCE_THRESHOLD
    if threshold is not None:
        reflection.REFLECTION_IMPORTANCE_THRESHOLD = threshold
    stub = StubProvider()
    saved = dict(providers._instances)
    saved_cfg = (config.PROVIDER, config.CHAT_MODEL)
    saved_exec, saved_city = world.ThreadPoolExecutor, simulation.citystate
    saved_roster = simulation._active_roster
    # world._meet flushes the agents it touched by iterating a *set* of
    # Agent objects, whose order follows their memory addresses -- a
    # stable name-based hash makes that order repeatable here.
    Agent.__hash__ = lambda self: _h(self.name) % (1 << 61)
    providers._instances["ollama"] = stub
    world.ThreadPoolExecutor = SerialExecutor
    simulation.citystate = StubCitystate()
    simulation._active_roster = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            simulation.run(provider="ollama", agent_names=None, **params)
        events = recorder.to_dict()["events"]
    finally:
        providers._instances.clear()
        providers._instances.update(saved)
        config.PROVIDER, config.CHAT_MODEL = saved_cfg
        world.ThreadPoolExecutor, simulation.citystate = saved_exec, saved_city
        simulation._active_roster = saved_roster
        del Agent.__hash__
        reflection.REFLECTION_IMPORTANCE_THRESHOLD = saved_threshold
    return {
        "agents": [a["name"] for a in recorder.get_agents()],
        "events": [[e["kind"], e.get("agent"), e["tick"]] for e in events],
        "prompt_count": len(stub.prompts),
        "prompts_sha256": hashlib.sha256("\n\x00\n".join(stub.prompts).encode()).hexdigest(),
    }


class SceneRegression(unittest.TestCase):
    maxDiff = None

    def _check(self, name: str):
        got = run_scenario(SCENARIOS[name])
        path = GOLDEN / f"scene_{name}.json"
        if os.environ.get("UPDATE_GOLDEN"):
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(got, indent=1) + "\n")
        want = json.loads(path.read_text())
        self.assertEqual(want["agents"], got["agents"])
        self.assertEqual(want["events"], got["events"])
        self.assertEqual(want["prompt_count"], got["prompt_count"])
        self.assertEqual(want["prompts_sha256"], got["prompts_sha256"])

    def test_grounded(self):
        self._check("grounded")

    def test_convened(self):
        self._check("convened")

    def test_reflective(self):
        self._check("reflective")

    def test_deterministic(self):
        self.assertEqual(run_scenario(SCENARIOS["grounded"]), run_scenario(SCENARIOS["grounded"]))


if __name__ == "__main__":
    unittest.main()
