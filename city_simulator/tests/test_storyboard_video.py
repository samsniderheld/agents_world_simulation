"""Treatment -> storyboard -> reference-to-video prompt (agents/treatment.py's
parse_treatment, agents/storyboard_video.py)."""
import re
import tempfile
import unittest
from pathlib import Path

from agents import storyboard_video as sv
from agents import treatment

TREATMENT = '''CHARACTERS:
- Lou Marsh -- a tired janitor
- Vera Klein -- the diner owner

SYNOPSIS:
Lou finishes his night shift and drifts into Vera's diner. She pours him coffee without asking. Nothing much is said. He leaves a coin.

STORYBOARD:
1. Background: A school corridor at dawn, polished floor reflecting low sun. Wide shot, eye level. | Action: Lou pushes a wide broom down the hall. The camera holds a static shot.
2. Background: A diner counter seen through a fogged window. | Action: Vera pours coffee and says: "Long night, Lou?" Lou Marsh nods. A trucker at the end mutters, "Same as always". The camera pushes in with small amplitude at slow speed.
3. Background: A street corner under a red neon sign reading "OPEN". | Action: Lou steps out. Vera calls out "Don't be a stranger." The camera pans right.

SOUNDSCAPE: Broom bristles brush the floor, and cups clink.

MUSIC: Sparse piano at a slow tempo.
'''


class ParseTreatment(unittest.TestCase):
    def test_parts(self):
        p = treatment.parse_treatment(TREATMENT)
        self.assertEqual(p["characters"], ["Lou Marsh", "Vera Klein"])
        self.assertEqual(len(p["shots"]), 3)
        self.assertTrue(p["shots"][1]["action"].startswith("Vera pours coffee"))
        self.assertEqual(p["soundscape"], "Broom bristles brush the floor, and cups clink.")
        self.assertEqual(p["music"], "Sparse piano at a slow tempo.")

    def test_frames_paint_only_the_backgrounds(self):
        shots = treatment.parse_storyboard_shots(TREATMENT)
        self.assertEqual(len(shots), 3)
        self.assertTrue(shots[0].startswith("A school corridor at dawn"))
        self.assertTrue(all(s.endswith("No people in the frame.") for s in shots))
        self.assertFalse(any("Lou" in s or "camera" in s for s in shots))

    def test_old_treatments_still_parse(self):
        old = "STORYBOARD:\n1. A diner at night | Character: Lou | DOP: wide\n2. A street | Lighting: dusk\n"
        self.assertEqual(treatment.parse_storyboard_shots(old), ["A diner at night | Character: Lou | DOP: wide",
                                                                 "A street | Lighting: dusk"])


class BuildPrompt(unittest.TestCase):
    def setUp(self):
        self.parsed = treatment.parse_treatment(TREATMENT)
        cast = [{"name": "Lou Marsh", "image_path": "/lou.png"},
                {"name": "Vera Klein", "image_path": None, "appearance": "A stout woman with a gray bun. Kind."}]
        paths, self.cast, self.bgs, self.warnings = sv.pick_pictures(cast, ["/b1.png", "/b2.png", None])
        self.paths = paths
        self.prompt = sv.build_prompt(self.parsed, self.cast, self.bgs, 15, visual_look="soft window light")

    def test_pictures_cast_first_then_backgrounds(self):
        self.assertEqual(self.paths, ["/lou.png", "/b1.png", "/b2.png"])
        self.assertEqual([c["picture"] for c in self.cast], [1, None])
        self.assertEqual(self.bgs, [2, 3, None])
        self.assertTrue(any("Vera Klein has no picture" in w for w in self.warnings))
        self.assertTrue(any("shot 3" in w for w in self.warnings))

    def test_sections_in_order(self):
        heads = [l for l in self.prompt.splitlines() if re.match(r"^[a-z_]+:$", l)]
        self.assertEqual(heads, ["subject_definitions:", "summary:", "retention_analysis:",
                                 "detailed_description:", "overall_soundscape:", "non_diegetic_music:"])
        self.assertIn("[reference generation]", self.prompt)

    def test_subjects_and_pictures(self):
        self.assertIn("<Subject 1> is Lou Marsh, the person in <Picture 1>", self.prompt)
        self.assertIn("<Subject 2> is Vera Klein: A stout woman with a gray bun.", self.prompt)
        self.assertIn("<Subject 3> is the setting of [Shot 1] in <Picture 2>: a school corridor at dawn", self.prompt)
        self.assertIn("<Subject 5> is the setting of [Shot 3]: a street corner", self.prompt)
        self.assertIn("<Subject 1> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved", self.prompt)

    def test_shots_cut_on_time(self):
        lines = [l for l in self.prompt.splitlines() if l.startswith("[Shot")]
        self.assertTrue(lines[0].startswith("[Shot 1] The shot opens in <Subject 3>"))
        self.assertTrue(lines[1].startswith("[Shot 2] At 00:05.000, the camera cuts to <Subject 4>"))
        self.assertTrue(lines[2].startswith("[Shot 3] At 00:10.000, the camera cuts to <Subject 5>"))

    def test_speakers_and_dialogue(self):
        self.assertIn('<Subject 2> (S1) pours coffee and says: <d>[English] Long night, Lou?</d>', self.prompt)
        self.assertIn('A trucker at the end (S2) mutters: <d>[English] Same as always.</d> The camera', self.prompt)
        self.assertIn('<Subject 2> (S1) calls out: <d>[English] Don\'t be a stranger.</d>', self.prompt)
        self.assertIn('a red neon sign reading "OPEN"', self.prompt)           # on-screen text stays quoted
        self.assertNotIn("Vera", self.prompt.split("detailed_description:")[1].split("overall_soundscape")[0])

    def test_sound(self):
        self.assertIn("overall_soundscape:\nBroom bristles", self.prompt)
        self.assertIn("non_diegetic_music:\nSparse piano", self.prompt)

    def test_names_with_a_quoted_nickname(self):
        parsed = treatment.parse_treatment(
            'STORYBOARD:\n1. Background: A bar. | Action: Augie wipes the counter. Auguste "Augie" Worthington '
            'says: "Last call." The camera holds a static shot.\n')
        cast = [{"name": 'Auguste "Augie" Worthington', "picture": 1}]
        prompt = sv.build_prompt(parsed, cast, [2], 10)
        self.assertIn('[Shot 1] The shot opens in <Subject 2>: a bar. <Subject 1> wipes the counter. '
                      '<Subject 1> (S1) says: <d>[English] Last call.</d> The camera holds a static shot.', prompt)

    def test_timestamp(self):
        self.assertEqual(sv.timestamp(2.5), "00:02.500")
        self.assertEqual(sv.timestamp(65), "01:05.000")

    def test_picture_limit(self):
        cast = [{"name": f"P{i}", "image_path": f"/p{i}.png"} for i in range(5)]
        paths, cast, numbers, warnings = sv.pick_pictures(cast, [f"/b{i}.png" for i in range(6)])
        self.assertEqual(len(paths), sv.MAX_PICTURES)
        self.assertEqual([c["picture"] for c in cast], [1, 2, 3, None, None])
        self.assertEqual(numbers, [4, 5, 6, 7, 8, 9])


class Prepare(unittest.TestCase):
    def test_from_a_city_and_storyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            def f(name):
                p = Path(tmp) / name
                p.write_bytes(b"x")
                return str(p)
            city = {"characters": [{"id": "c1", "name": "Lou Marsh", "bio": "A lean man."},
                                   {"id": "c2", "name": "Vera Klein", "bio": "A stout woman."}],
                    "media": {"c1": [{"id": "m1", "kind": "image", "local_path": f("old.png"), "url": "a/old.png"},
                                     {"id": "m2", "kind": "image", "local_path": f("sheet.png"), "url": "a/sheet.png"}],
                              "p1": [{"id": "m9", "kind": "image", "local_path": f("bg2.png"), "url": "p/bg2.png"}]}}
            storyboard = {"nodes": [
                {"type": "frame", "data": {"shotIndex": 0, "localPath": f("bg1.png"), "url": "out/bg1.png"}},
                {"type": "frame", "data": {"shotIndex": 1, "mediaId": "m9", "attachTo": "p1"}},
                {"type": "frame", "data": {"shotIndex": 2}},                    # not made yet
                {"type": "agent", "data": {"characterId": "c1"}}]}
            out = sv.prepare(city, [], storyboard, TREATMENT, [], 15, visual_look="soft")
            self.assertEqual([Path(p).name for p in out["image_paths"]], ["sheet.png", "bg1.png", "bg2.png"])
            self.assertEqual([(p["number"], p["kind"], p["url"]) for p in out["pictures"]],
                             [(1, "character", "a/sheet.png"), (2, "background", "out/bg1.png"),
                              (3, "background", "p/bg2.png")])
            self.assertIn("Vera Klein has no picture -- described from their bio instead", out["warnings"])
            self.assertIn("shot 3 has no background image yet", out["warnings"])
            self.assertIn("<Subject 2> is Vera Klein: A stout woman.", out["prompt"])

    def test_no_shots(self):
        with self.assertRaises(ValueError):
            sv.prepare({"characters": []}, [], {"nodes": []}, "SYNOPSIS:\nnothing", [], 15)


if __name__ == "__main__":
    unittest.main()
