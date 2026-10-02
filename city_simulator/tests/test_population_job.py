"""history/population.py: the Population node's job, with and without the
visual assets (portraits and exterior photos)."""

import unittest
from unittest import mock

from history import population


class FakeCity:
    def __init__(self):
        self.city = {"places": [{"id": f"place_{i}", "name": f"Place {i}", "status": "active", "place_type": "Tavern/Bar",
                                 "founded_year": 1900 + i} for i in range(3)],
                     "figures": [], "characters": [], "media": {}}
        self.added, self.media = [], []

    def get(self):
        return self.city

    def add_character(self, c):
        self.added.append(c)
        return c

    def add_media(self, entity_id, kind, url, local_path="", prompt="", tag=""):
        self.media.append((entity_id, tag))


def fake_resident(places, figures, force_place_id=None, **kw):
    return {"id": f"char_{force_place_id}", "name": f"Resident of {force_place_id}", "age": 40,
            "occupation": "bartender", "bio": "A local.", "place_id": force_place_id}


class PopulationJobTests(unittest.TestCase):
    def _run(self, with_images):
        city = FakeCity()
        images = mock.Mock(return_value=("url", "/tmp/x.png", "prompt"))
        with mock.patch.object(population, "citystate", city), \
                mock.patch.object(population.characters, "generate_one", side_effect=fake_resident), \
                mock.patch.object(population, "_square_image", images):
            population._worker(3, lambda: None, None, None, with_images)
        return city, images, population.get_status()

    def test_without_images(self):
        city, images, status = self._run(False)
        self.assertEqual(len(city.added), 3)
        images.assert_not_called()
        self.assertEqual(city.media, [])
        self.assertEqual((status["phase"], status["total"], status["error"]), ("done", 3, None))

    def test_with_images(self):
        city, images, status = self._run(True)
        self.assertEqual(len(city.added), 3)
        self.assertEqual(images.call_count, 6)                      # 3 portraits + 3 exteriors
        self.assertEqual(sorted(tag for _, tag in city.media), ["exterior"] * 3 + ["portrait"] * 3)
        self.assertEqual(status["total"], 6)


if __name__ == "__main__":
    unittest.main()
