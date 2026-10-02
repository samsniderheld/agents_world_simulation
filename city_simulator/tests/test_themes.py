"""City themes (theme.py): the built-in themes validate, a theme drives
history and both simulation modes, cities keep their own theme, uploads are
validated with useful messages."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

import theme
from agents.city import prompts as city_prompts
from agents.city.stub_server import StubServer
from tests.city_fixtures import run_city


class BuiltInThemes(unittest.TestCase):
    def test_both_validate_and_dry_run(self):
        for theme_id in ("noir_nyc", "fantasy_realm"):
            t = theme.get(theme_id)
            self.assertEqual(theme.validate(t), [], theme_id)
            self.assertEqual(theme.dry_run(t), [], theme_id)

    def test_fantasy_history(self):
        from history import config, generate
        t = theme.get("fantasy_realm")
        saved = config.LLM_FILL_NAMES
        config.LLM_FILL_NAMES = False
        try:
            with theme.use(t), contextlib.redirect_stdout(io.StringIO()):
                figures, places, events = generate.generate(seed=2, figures_per_era=2, events_per_figure=3)
                payload = generate.to_json(figures, places, events)
        finally:
            config.LLM_FILL_NAMES = saved
        self.assertEqual(payload["theme"]["id"], "fantasy_realm")
        self.assertEqual(payload["eras"][0]["start_year"], 1000)
        place_types = set(t["entities"]["place_types"])
        self.assertTrue(all(p["place_type"] in place_types for p in payload["places"]))
        self.assertTrue(all(1000 <= e["year"] <= 1312 for e in payload["events"]))

    def test_city_run_uses_the_theme(self):
        server = StubServer(reply_fn=city_prompts.stub_reply)
        theme.pin(theme.get("fantasy_realm"))
        try:
            run_city(server, ticks=2, background_count=20)
        finally:
            theme.pin(theme.default())
        joined = "\n".join(server.prompts)
        self.assertIn("Aldermere", joined)
        self.assertNotIn("New York", joined)

    def test_scene_fallback_cast_follows_the_theme(self):
        from agents import simulation
        saved = simulation._active_roster
        simulation._active_roster = None
        try:
            with theme.use(theme.get("fantasy_realm")):
                self.assertIn("Brannoc", simulation.roster_summary()[0]["name"])
            self.assertEqual(simulation.roster_summary()[0]["name"], "Oswald")
        finally:
            simulation._active_roster = saved


class OptionalPrompts(unittest.TestCase):
    def test_older_copy_of_the_default_theme_falls_back(self):
        """A city's theme.yaml copied before the Dice & DM prompts existed
        has the default theme's id but no prompts.dm -- it still works."""
        raw = yaml.safe_load((theme.BUILTIN_DIR / f"{theme.DEFAULT_ID}.yaml").read_text())
        raw["prompts"].pop("dm")
        raw["city_life"].pop("dice")
        old = theme.parse(yaml.safe_dump(raw), source="city", check=False)
        self.assertEqual(old.id, theme.DEFAULT_ID)
        self.assertEqual(old.template("dm.sheet"), theme.default().template("dm.sheet"))
        with self.assertRaises(KeyError):
            theme.default().template("dm.no_such_prompt")
        from agents.dm import background
        with theme.use(old):
            self.assertIn("work", background.table()["activities"])


class Rendering(unittest.TestCase):
    def test_only_lowercase_slots_are_filled(self):
        self.assertEqual(theme.fill('Say {name}. Reply as JSON: {"items": [1]} and {Keep}', {"name": "hi"}),
                         'Say hi. Reply as JSON: {"items": [1]} and {Keep}')
        with self.assertRaises(KeyError):
            theme.fill("{missing}", {})


class CityThemes(unittest.TestCase):
    def setUp(self):
        from citystate import store
        self.store = store
        self.tmp = Path(tempfile.mkdtemp(prefix="themetest_"))
        self.saved = (store._CITIES_DIR, store._ACTIVE_FILE, store._cache, store._loaded, store._active_id,
                      theme.UPLOAD_DIR)
        store._CITIES_DIR = self.tmp / "cities"
        store._ACTIVE_FILE = self.tmp / "active_city"
        theme.UPLOAD_DIR = self.tmp / "themes"
        for city in ("city_a", "city_b"):
            (self.tmp / "cities" / city).mkdir(parents=True)
            (self.tmp / "cities" / city / "city.json").write_text("{}")
        store.save_city_theme("city_b", theme.get("fantasy_realm").text)
        store._cache, store._loaded, store._active_id = None, False, None
        theme.pin(None)

    def tearDown(self):
        s = self.store
        s._CITIES_DIR, s._ACTIVE_FILE, s._cache, s._loaded, s._active_id, theme.UPLOAD_DIR = self.saved
        theme.pin(theme.default())
        shutil.rmtree(self.tmp)

    def test_current_follows_the_active_city(self):
        self.store._ACTIVE_FILE.write_text("city_a")
        self.store._loaded = False
        self.assertEqual(theme.current().id, "noir_nyc")           # no copy: the default
        self.store.set_active("city_b")
        self.assertEqual(theme.current().id, "fantasy_realm")
        with theme.use(theme.default()):
            self.assertEqual(theme.current().id, "noir_nyc")       # an explicit use() wins

    def _upload_text(self, **changes):
        raw = yaml.safe_load(theme.get("fantasy_realm").text)
        raw["theme"]["id"] = "my_world"
        for path, value in changes.items():
            node = raw
            parts = path.split(".")
            for p in parts[:-1]:
                node = node[p]
            node[parts[-1]] = value
        return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)

    def test_upload_valid(self):
        t = theme.save_upload(self._upload_text())
        self.assertEqual(t.id, "my_world")
        self.assertIn("my_world", [x["id"] for x in theme.list_themes()])
        self.assertTrue(theme.delete_upload("my_world"))
        self.assertFalse(theme.delete_upload("noir_nyc"))

    def test_upload_problems_are_specific(self):
        cases = {
            "prompts.scene.plan": ("{identity} {favourite_color}", "{favourite_color}"),
            "prompts.scene.where": ("Where should {name} go?", "WHERE:"),
            "names.era_name_groups": ({"founding": "nope"}, "unknown group 'nope'"),
            "city_life.work_roles": ({"Laser Tag": ["ref"]}, "Laser Tag"),
            "theme.id": ("noir_nyc", "built-in default"),
        }
        for path, (value, expected) in cases.items():
            with self.assertRaises(theme.ThemeError) as ctx:
                theme.save_upload(self._upload_text(**{path: value}))
            self.assertTrue(any(expected in p for p in ctx.exception.problems), (path, ctx.exception.problems))

    def test_upload_not_yaml(self):
        with self.assertRaises(theme.ThemeError):
            theme.save_upload("theme: [unclosed")


if __name__ == "__main__":
    unittest.main()
