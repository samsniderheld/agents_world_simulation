"""visuals/providers/comfyui.py: the workflow is adapted to any number of
input images, and a whole call runs against a stand-in ComfyUI server
(upload -> /prompt -> /history -> /view) without a real one."""

import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from visuals import config
from visuals.providers import comfyui

SPEC = config.COMFYUI["image_workflow"]
TEMPLATE = json.loads((Path(config.COMFYUI_DIR) / SPEC["file"]).read_text())


def image_inputs(graph, node):
    return {k: v for k, v in graph[node]["inputs"].items() if k.startswith("images.")}


class PrepareGraph(unittest.TestCase):
    def test_grows_to_any_number_of_images(self):
        for n in (1, 2, 4):
            names = [f"city_simulator/img{i}.png" for i in range(n)]
            g = comfyui.prepare_graph(TEMPLATE, SPEC, "a quiet morning", names, seed=42, size=(1664, 928))
            loaders = sorted(nid for nid, node in g.items() if node["class_type"] == "LoadImage")
            self.assertEqual(loaders, [f"cs_image_{i + 1}" for i in range(n)])
            self.assertEqual([g[l]["inputs"]["image"] for l in loaders], names)
            # the encoder numbers from 1, the batch node from 0 -- each kept its own scheme
            self.assertEqual(image_inputs(g, "459:474"), {f"images.image_{i + 1}": [f"cs_image_{i + 1}", 0] for i in range(n)})
            self.assertEqual(image_inputs(g, "459:485"), {f"images.image{i}": [f"cs_image_{i + 1}", 0] for i in range(n)})
            self.assertNotIn("470", g)
            self.assertNotIn("472", g)                 # the Compare node doesn't feed the output
            self.assertEqual(g["459:500"]["inputs"]["prompt"], "a quiet morning")
            self.assertEqual(g["459:458"]["inputs"]["seed"], 42)
            self.assertEqual(g["459:500"]["inputs"]["sampling_mode.seed"], 42)
            self.assertEqual(g["459:468"]["inputs"]["switch"], False)

    def test_text_to_image(self):
        g = comfyui.prepare_graph(TEMPLATE, SPEC, "a quiet morning", [], seed=1, size=(1328, 1328))
        self.assertFalse([n for n in g.values() if n["class_type"] in ("LoadImage", "TextGenerate", "BatchImagesNode")])
        self.assertEqual(g["459:474"]["inputs"]["prompt"], "a quiet morning")   # straight to the encoder
        self.assertEqual(image_inputs(g, "459:474"), {})
        self.assertEqual(g["459:468"]["inputs"]["switch"], True)              # from the empty latent
        self.assertEqual((g["459:456"]["inputs"]["width"], g["459:456"]["inputs"]["height"]), (1328, 1328))
        # every link points at a node that's still there
        for node in g.values():
            for v in node["inputs"].values():
                if comfyui._is_link(v):
                    self.assertIn(v[0], g)

    def test_template_untouched(self):
        before = json.dumps(TEMPLATE, sort_keys=True)
        comfyui.prepare_graph(TEMPLATE, SPEC, "x", ["a.png", "b.png", "c.png"], seed=1)
        self.assertEqual(before, json.dumps(TEMPLATE, sort_keys=True))


class FakeComfy(BaseHTTPRequestHandler):
    """Just enough of ComfyUI's HTTP API."""
    uploads, prompts = [], []
    fail_validation = False

    def log_message(self, *a):
        pass

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        if self.path == "/upload/image":
            name = body.split(b'filename="')[1].split(b'"')[0].decode()
            FakeComfy.uploads.append(name)
            return self._json(200, {"name": name, "subfolder": "city_simulator", "type": "input"})
        if self.path == "/prompt":
            if FakeComfy.fail_validation:
                return self._json(400, {"error": {"message": "Prompt outputs failed validation"},
                                        "node_errors": {"459:451": {"class_type": "UNETLoader", "errors": [
                                            {"message": "Value not in list", "details": "unet_name: 'x' not in []"}]}}})
            FakeComfy.prompts.append(json.loads(body)["prompt"])
            return self._json(200, {"prompt_id": "p1", "number": 1})
        self._json(404, {})

    def do_GET(self):
        if self.path.startswith("/history/p1"):
            return self._json(200, {"p1": {"status": {"status_str": "success", "completed": True},
                                           "outputs": {"461": {"images": [
                                               {"filename": "Qwen_image_2.1_00001_.png", "subfolder": "", "type": "output"}]}}}})
        if self.path.startswith("/view"):
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (64, 36), "white").save(buf, format="PNG")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            return self.wfile.write(buf.getvalue())
        self._json(404, {})


class ProviderAgainstFakeServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        # results land in a temp copy of visuals/data/{uploads,outputs}, not the real one
        cls.patches = [mock.patch.object(config, "OUTPUTS_DIR", Path(cls.tmp.name) / "outputs"),
                       mock.patch.object(config, "UPLOADS_DIR", Path(cls.tmp.name) / "uploads")]
        for p in cls.patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def setUp(self):
        FakeComfy.uploads, FakeComfy.prompts, FakeComfy.fail_validation = [], [], False
        self.provider = comfyui.ComfyUIProvider(base_url=f"http://127.0.0.1:{self.server.server_port}")

    def _images(self, n):
        from PIL import Image
        paths = []
        for i in range(n):
            p = Path(self.tmp.name) / f"ref{i}.png"
            Image.new("RGB", (8, 8), (i * 40, 0, 0)).save(p)
            paths.append(str(p))
        return paths

    def test_three_images(self):
        out = self.provider.generate_image("Lou at the counter", image_paths=self._images(3), aspect_ratio="16:9")
        self.assertEqual(len(FakeComfy.uploads), 3)
        graph = FakeComfy.prompts[0]
        self.assertEqual(len(image_inputs(graph, "459:474")), 3)
        self.assertTrue(all(graph[f"cs_image_{i}"]["inputs"]["image"].startswith("city_simulator/") for i in (1, 2, 3)))
        self.assertEqual((graph["459:456"]["inputs"]["width"], graph["459:456"]["inputs"]["height"]), (1664, 928))
        img = out["images"][0]
        self.assertTrue(Path(img["local_path"]).exists())
        self.assertEqual((img["width"], img["height"]), (64, 36))

    def test_more_images_than_the_model_takes(self):
        out = self.provider.generate_image("x", image_paths=self._images(6))
        self.assertEqual(len(FakeComfy.uploads), SPEC["max_images"])
        self.assertEqual(out["dropped_images"], 6 - SPEC["max_images"])

    def test_same_image_twice_uploads_one_name(self):
        path = self._images(1)[0]
        self.provider.generate_image("x", image_paths=[path, path])
        self.assertEqual(len(set(FakeComfy.uploads)), 1)

    def test_validation_error_is_readable(self):
        FakeComfy.fail_validation = True
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.generate_image("x")
        self.assertIn("node 459:451 (UNETLoader): unet_name", str(ctx.exception))

    def test_unreachable_server(self):
        p = comfyui.ComfyUIProvider(base_url="http://127.0.0.1:9")
        with self.assertRaises(RuntimeError) as ctx:
            p.generate_image("x")
        self.assertIn("Could not reach ComfyUI", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
