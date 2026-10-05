"""agents/people.py: one page shape for heroes and background residents."""

import unittest

from agents import people
from tests.city_fixtures import fake_storage, run_city

KEYS = {"id", "kind", "name", "age", "occupation", "quirk", "bio", "places", "life", "sheet", "plans", "memories",
        "people", "last_city_run", "runs", "treatments", "media", "resident_id", "can_make_hero"}


class People(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world, _ = run_city(ticks=3, background_count=30, dm=True, seed=5)
        cls.storage = cls.world.storage

    def test_hero_and_resident_share_one_shape(self):
        with fake_storage(self.storage):
            hero = people.person("char_0")
            resident = people.person(self.storage.background[0]["id"])
        self.assertLessEqual(KEYS, set(hero))
        self.assertLessEqual(KEYS, set(resident))
        self.assertEqual((hero["kind"], resident["kind"]), ("hero", "resident"))
        self.assertTrue(hero["memories"] and hero["runs"] and hero["last_city_run"]["stays"])
        self.assertNotIn("embedding", hero["runs"][0]["events"][0])
        self.assertFalse(any(e["kind"] == "memory" for r in hero["runs"] for e in r["events"]))
        self.assertTrue(resident["can_make_hero"] and not hero["can_make_hero"])
        self.assertEqual(set(hero["sheet"]["stats"]), {"STR", "DEX", "CON", "INT", "WIS", "CHA"})
        self.assertTrue(any(p["meetings"] for p in hero["people"]))

    def test_unknown(self):
        with fake_storage(self.storage), self.assertRaises(ValueError):
            people.person("bg_nope")

    def test_a_resident_made_a_hero_is_the_hero(self):
        resident = dict(self.storage.background[1], promoted_to="char_1")
        storage = self.storage
        saved = storage.background[1]
        storage.background[1] = resident
        try:
            with fake_storage(storage):
                page = people.person(resident["id"])
        finally:
            storage.background[1] = saved
        self.assertEqual((page["kind"], page["id"], page["resident_id"]), ("hero", "char_1", resident["id"]))


if __name__ == "__main__":
    unittest.main()
