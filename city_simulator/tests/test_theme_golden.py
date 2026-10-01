"""Golden snapshots of everything the theme file now drives, recorded before
the content moved out of the code: history generation (grammar path and
every prompt the LLM path sends), CITY prompts and events, background
residents, treatments, portrait/exterior prompts, and the zoom/insight
prompts. With the default theme (themes/noir_nyc.yaml) every one must match
exactly -- the SCENE regression test covers SCENE the same way.

    python -m unittest tests.test_theme_golden                    # check
    UPDATE_GOLDEN=1 python -m unittest tests.test_theme_golden    # re-record
"""

import contextlib
import hashlib
import io
import json
import os
import random
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

GOLDEN = Path(__file__).parent / "golden" / "theme_baseline.json"
_ID = re.compile(r"\b(fig|place|char|evt|media)_[0-9a-f]{8}\b")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _normalise_ids(obj):
    """uuid-based ids -> stable ids in order of first appearance."""
    text = json.dumps(obj, sort_keys=True, default=str)
    seen = {}

    def repl(m):
        return seen.setdefault(m.group(0), f"{m.group(1)}_{len(seen):04d}")
    return json.loads(_ID.sub(repl, text))


def _fake_history_llm(prompt, model=None, temperature=0.7, context_tokens=None, timeout=None):
    h = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16)
    if "NAME: <full name>" in prompt:
        return (f"NAME: Resident {h % 997} Smith\nAGE: {20 + h % 50}\nOCCUPATION: worker {h % 13}\n"
                f"QUIRK: hums {h % 7}\nBIO: A person with a past number {h % 101}.")
    if "<year>: <event sentence>" in prompt:
        return "\n".join(f"{1900 + (h >> k) % 59}: life event {k}." for k in range(4))
    if "person name" in prompt:
        return f"Name{h % 89} Surname{h % 83}"
    if "place name" in prompt or "business/place name" in prompt:
        return f"Place {h % 71}"
    if "Describe, in exactly one vivid sentence" in prompt:
        return f"A building with a facade number {h % 97}, of brick and glass."
    if "Rewrite the following sentence" in prompt:
        return f"Rewritten event {h % 53}."
    if "short narrative summary" in prompt:
        return f"Summary {h % 1000}."
    return f"reply {h % 1000}"


def history_snapshot(use_llm: bool) -> dict:
    from history import characters, config, generate, llm, summary
    prompts = []

    def recorder(prompt, **kw):
        prompts.append(prompt)
        return _fake_history_llm(prompt, **kw)
    saved = (config.LLM_FILL_NAMES, config.LLM_FLOURISH_RATE)
    patches = [mock.patch.object(llm, "available", return_value=use_llm),
               mock.patch.object(llm, "complete", side_effect=recorder)]
    try:
        for p in patches:
            p.start()
        config.LLM_FILL_NAMES = use_llm
        config.LLM_FLOURISH_RATE = 0.5 if use_llm else 0.0
        with contextlib.redirect_stdout(io.StringIO()):
            figures, places, events_list = generate.generate(seed=7, figures_per_era=2, events_per_figure=4)
            chars = characters.generate_characters(places, figures, count=4, seed=7)
            one = characters.generate_one(places, figures, occupation="night watchman", sex="a woman", seed=3)
            from history import eras
            text = summary.generate_summary(figures, places, events_list, eras.all_eras())
        payload = generate.to_json(figures, places, events_list, characters_list=chars + [one], summary_text=text)
    finally:
        for p in patches:
            p.stop()
        config.LLM_FILL_NAMES, config.LLM_FLOURISH_RATE = saved
    payload.pop("generated_at")
    payload.pop("theme", None)
    norm = _normalise_ids(payload)
    return {"output": _h(json.dumps(norm, sort_keys=True)), "places": len(norm["places"]),
            "events": len(norm["events"]), "prompts": [_h(p) for p in prompts],
            "sample": {"place": norm["places"][0]["name"], "event": norm["events"][0]["gospel_text"],
                       "character": norm["characters"][0]["bio"][:120]}}


def city_snapshot() -> dict:
    from agents.city import prompts, recorder
    from agents.city import population as pop
    from agents.city.stub_server import StubServer
    from tests.city_fixtures import fake_city, run_city
    server = StubServer(reply_fn=prompts.stub_reply)
    run_city(server, ticks=3, background_count=40, directive="a payroll went missing")
    events = [[e["kind"], e.get("agent"), e["tick"]] for e in recorder.query(0, tier="all", limit=None)["events"]
              if e["kind"] not in ("metrics", "status")]
    residents = pop.generate(fake_city(), 200, seed=3)
    blocks = [[b.place, b.start, b.end, b.activity] for r in residents[:30]
              for b in pop.template_schedule(SimpleNamespace(**{**r, "occupation": r["occupation"]}), random.Random(1))]
    return {"prompts": [_h(p) for p in server.prompts], "events": _h(json.dumps(events)),
            "residents": _h(json.dumps(residents, sort_keys=True)), "schedules": _h(json.dumps(blocks)),
            "prefix": _h(prompts.city_prefix(fake_city()))}


def misc_prompts() -> dict:
    from agents import treatment
    from agents.city import prompts
    from history import population
    captured = []
    with mock.patch("agents.llm.complete", side_effect=lambda p, **kw: captured.append(p) or "T"):
        treatment.generate_treatment(
            ["[06:00 AM] Lou (Ozzy's Bar): wipes the bar", "[06:30 AM] Vera: Hello."], ["Lou", "Vera"],
            location_details=[{"name": "Ozzy's Bar", "architecture": "a brick saloon"}, {"name": "Pier 9", "architecture": ""}],
            cast_details=[{"name": "Lou", "bio": "A tired detective."}, {"name": "Vera", "bio": ""}],
            directive="a payroll went missing")
        treatment.generate_treatment([], ["Lou"])
    char = {"name": "Lou Marino", "age": 45, "occupation": "private eye", "bio": "A tired detective."}
    place = {"name": "Ozzy's Bar", "architecture": "A brick saloon."}
    b = SimpleNamespace(name="Pearl Rizzo", age=33, occupation="sound engineer", bio="Pearl fixes radios.",
                        work="Greenhaven", haunt="Ozzy's Bar")
    return {
        "treatment": [_h(p) for p in captured],
        "portrait": _h(population._portrait_prompt(char)),
        "exterior": _h(population._exterior_prompt(place, "tavern")),
        "bio_upgrade": _h(prompts.bio_upgrade(b, "Ozzy's Bar")),
        "report": _h(prompts.city_report("HEADER", ["line a", "line b"], "old briefing")),
        "question": _h(prompts.city_question("HEADER", ["line a"], "who knows?")),
        "narrator": _h(prompts.NARRATOR_TIER), "hero_tier": _h(prompts.HERO_TIER),
        "background_tier": _h(prompts.BACKGROUND_TIER),
    }


def snapshot() -> dict:
    return {"history_grammar": history_snapshot(False), "history_llm": history_snapshot(True),
            "city": city_snapshot(), "misc": misc_prompts()}


class ThemeGolden(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.got = snapshot()
        if os.environ.get("UPDATE_GOLDEN"):
            GOLDEN.write_text(json.dumps(cls.got, indent=1) + "\n")
        cls.want = json.loads(GOLDEN.read_text())

    def _check(self, area):
        want, got = self.want[area], self.got[area]
        for key in want:
            if isinstance(want[key], list) and isinstance(got.get(key), list) and want[key] != got[key]:
                first = next((i for i, (a, b) in enumerate(zip(want[key], got[key])) if a != b), min(len(want[key]), len(got[key])))
                self.fail(f"{area}.{key}: first difference at item {first} (of {len(want[key])} vs {len(got[key])})")
            self.assertEqual(want[key], got.get(key), f"{area}.{key}")

    def test_history_grammar(self):
        self._check("history_grammar")

    def test_history_llm_prompts(self):
        self._check("history_llm")

    def test_city(self):
        self._check("city")

    def test_misc_prompts(self):
        self._check("misc")


if __name__ == "__main__":
    unittest.main()
