"""visuals/providers/comfyui.py: the workflow is fitted to any number of
input images, and a whole call runs against a stand-in ComfyUI server
(upload -> /prompt -> /history -> /view)."""

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
VSPEC = config.COMFYUI["video_workflow"]
VTEMPLATE = json.loads((Path(config.COMFYUI_DIR) / VSPEC["file"]).read_text())


def image_inputs(graph, node):
    return {k: v for k, v in graph[node]["inputs"].items() if k.startswith("images.")}


class PrepareGraph(unittest.TestCase):
    def test_any_number_of_images(self):
        for n in (1, 2, 4):
            names = [f"city_simulator/img{i}.png" for i in range(n)]
            g = comfyui.prepare_graph(TEMPLATE, SPEC, "a quiet morning", names, seed=42, size=(1376, 768),
                                      resolution=1024)
            loaders = sorted(nid for nid, node in g.items() if node["class_type"] == "LoadImage")
            self.assertEqual(loaders, [f"cs_image_{i + 1}" for i in range(n)])
            self.assertEqual([g[l]["inputs"]["image"] for l in loaders], names)
            # the encoder numbers from 1, the batch node from 0 -- each keeps its own scheme
            self.assertEqual(image_inputs(g, "459:474"), {f"images.image_{i + 1}": [f"cs_image_{i + 1}", 0] for i in range(n)})
            self.assertEqual(image_inputs(g, "459:485"), {f"images.image{i}": [f"cs_image_{i + 1}", 0] for i in range(n)})
            self.assertNotIn("470", g)
            self.assertNotIn("472", g)                     # the Compare node doesn't feed the output
            self.assertEqual(g["459:500"]["inputs"]["prompt"], "a quiet morning")
            self.assertEqual(g["459:458"]["inputs"]["seed"], 42)
            self.assertEqual(g["459:500"]["inputs"]["sampling_mode.seed"], 42)
            # the canvas is the node's size (custom size on), references resized to the budget
            self.assertEqual(g["459:468"]["inputs"]["switch"], True)
            self.assertEqual((g["459:456"]["inputs"]["width"], g["459:456"]["inputs"]["height"]), (1376, 768))
            self.assertEqual(g["459:474"]["inputs"]["resolution"], 1024)

    def test_text_to_image(self):
        g = comfyui.prepare_graph(TEMPLATE, SPEC, "a quiet morning", [], seed=1, size=(1328, 1328))
        self.assertFalse([n for n in g.values() if n["class_type"] in ("LoadImage", "TextGenerate", "BatchImagesNode")])
        self.assertEqual(g["459:474"]["inputs"]["prompt"], "a quiet morning")
        self.assertEqual(g["459:468"]["inputs"]["switch"], True)
        self.assertEqual((g["459:456"]["inputs"]["width"], g["459:456"]["inputs"]["height"]), (1328, 1328))
        for node in g.values():                             # nothing points at a removed node
            for v in node["inputs"].values():
                if comfyui._is_link(v):
                    self.assertIn(v[0], g)

    def test_template_untouched(self):
        before = json.dumps(TEMPLATE, sort_keys=True)
        comfyui.prepare_graph(TEMPLATE, SPEC, "x", ["a.png", "b.png", "c.png"], seed=1)
        self.assertEqual(before, json.dumps(TEMPLATE, sort_keys=True))


class VideoGraph(unittest.TestCase):
    def test_first_frame_aspect_duration(self):
        settings = {VSPEC["aspect_ratio"]: VSPEC["aspect_ratios"]["16:9"], VSPEC["duration"]: 8.0}
        g = comfyui.prepare_graph(VTEMPLATE, VSPEC, "Lou walks out into the rain", ["city_simulator/frame.png"],
                                  seed=7, settings=settings)
        self.assertEqual(g["105:104"]["inputs"]["first_frame"], ["cs_image_1", 0])   # the source image
        self.assertEqual(g["cs_image_1"]["inputs"]["image"], "city_simulator/frame.png")
        self.assertEqual(g["105:104"]["inputs"]["prompt"], "Lou walks out into the rain")
        self.assertEqual(g["105:15"]["inputs"]["noise_seed"], 7)
        self.assertEqual(g["115"]["inputs"]["aspect_ratio"], "16:9 (Widescreen)")
        self.assertEqual(g["105:111"]["inputs"]["value"], 8.0)
        for gone in ("114", "119", "120"):     # the template image, and the unconnected size helpers
            self.assertNotIn(gone, g)

    def test_fixed_overrides(self):
        spec = {**VSPEC, "set": {"105:13.clip_name": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"}}
        g = comfyui.prepare_graph(VTEMPLATE, spec, "x", ["f.png"], seed=1)
        self.assertEqual(g["105:13"]["inputs"]["clip_name"], "qwen3vl_32b_minimax_h3_int8_convrot.safetensors")

    def test_needs_its_image(self):
        with self.assertRaises(ValueError):
            comfyui.prepare_graph(VTEMPLATE, VSPEC, "x", [], seed=1)


class ProviderChoice(unittest.TestCase):
    def test_defaults_fall_back_to_fal_for_what_comfyui_cant_do(self):
        from visuals import providers
        with mock.patch.object(config, "IMAGE_PROVIDER", "comfyui"), \
                mock.patch.object(config, "VIDEO_PROVIDER", "local"), mock.patch.object(config, "PROVIDER", "comfyui"):
            self.assertEqual(providers.default_for("image"), "comfyui")
            self.assertEqual(providers.default_for("video"), "fal")            # local can't make video
            self.assertEqual(providers.default_for("music"), "fal")
            self.assertEqual(providers.default_for("video_reference"), "fal")

    def test_refuses_what_a_provider_cant_do(self):
        from visuals import providers
        with self.assertRaises(RuntimeError):
            providers.provider_for("music", "comfyui")
        with self.assertRaises(RuntimeError):
            providers.provider_for("video", "local")
        with self.assertRaises(ValueError):
            providers.provider_for("image", "nope")
        self.assertIsInstance(providers.provider_for("video", "comfyui"), comfyui.ComfyUIProvider)


class CanvasSize(unittest.TestCase):
    def test_aspect_and_budget(self):
        self.assertEqual(comfyui.canvas_size("16:9", 1024), (1376, 768))
        self.assertEqual(comfyui.canvas_size("9:16", 2048), (1536, 2720))
        self.assertEqual(comfyui.canvas_size("1:1", 1024), (1024, 1024))
        self.assertEqual(comfyui.canvas_size("nonsense", 1024), (1024, 1024))


class FakeComfy(BaseHTTPRequestHandler):
    """Just enough of ComfyUI's HTTP API."""
    uploads, prompts, fail = [], [], None

    def log_message(self, *a):
        pass

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/upload/image":
            name = body.split(b'filename="')[1].split(b'"')[0].decode()
            FakeComfy.uploads.append(name)
            return self._json(200, {"name": name, "subfolder": "city_simulator", "type": "input"})
        if self.path == "/prompt":
            if FakeComfy.fail == "validation":
                return self._json(400, {"error": {"message": "Prompt outputs failed validation"},
                                        "node_errors": {"459:451": {"class_type": "UNETLoader", "errors": [
                                            {"message": "Value not in list", "details": "unet_name: 'x' not in []"}]}}})
            FakeComfy.prompts.append(json.loads(body)["prompt"])
            return self._json(200, {"prompt_id": "p1", "number": 1})
        self._json(404, {})

    def do_GET(self):
        if self.path.startswith("/history/p1"):
            if FakeComfy.fail == "execution":
                return self._json(200, {"p1": {"status": {"status_str": "error", "completed": False, "messages": [
                    ["execution_error", {"node_id": "459:458", "node_type": "KSampler",
                                         "exception_message": "CUDA out of memory"}]]}}})
            return self._json(200, {"p1": {"status": {"status_str": "success", "completed": True}, "outputs": {
                "461": {"images": [{"filename": "Qwen_image_2.1_00001_.png", "subfolder": "", "type": "output"}]},
                "92": {"images": [{"filename": "MiniMax_H3_00001_.mp4", "subfolder": "video", "type": "output"}],
                       "animated": [True]}}}})
        if self.path.startswith("/view") and ".mp4" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.end_headers()
            return self.wfile.write(b"\x00\x00\x00\x18ftypmp42fake-video")
        if self.path.startswith("/view"):
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (64, 36), "white").save(buf, format="PNG")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            return self.wfile.write(buf.getvalue())
        self._json(404, {})


class AgainstAStandInServer(unittest.TestCase):
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
        FakeComfy.uploads, FakeComfy.prompts, FakeComfy.fail = [], [], None
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
        out = self.provider.generate_image("Lou at the counter", image_paths=self._images(3), aspect_ratio="16:9",
                                           resolution="2K")
        self.assertEqual(len(FakeComfy.uploads), 3)
        graph = FakeComfy.prompts[0]
        self.assertEqual(len(image_inputs(graph, "459:474")), 3)
        self.assertTrue(all(graph[f"cs_image_{i}"]["inputs"]["image"].startswith("city_simulator/") for i in (1, 2, 3)))
        self.assertEqual((graph["459:456"]["inputs"]["width"], graph["459:456"]["inputs"]["height"]), (2720, 1536))
        self.assertEqual(graph["459:474"]["inputs"]["resolution"], 2048)
        img = out["images"][0]
        self.assertTrue(Path(img["local_path"]).exists())
        self.assertEqual((img["width"], img["height"]), (64, 36))

    def test_more_images_than_the_workflow_takes(self):
        self.provider.generate_image("x", image_paths=self._images(6))
        self.assertEqual(len(FakeComfy.uploads), SPEC["max_images"])

    def test_same_image_twice_is_one_file(self):
        path = self._images(1)[0]
        self.provider.generate_image("x", image_paths=[path, path])
        self.assertEqual(len(set(FakeComfy.uploads)), 1)

    def test_errors_name_the_node(self):
        FakeComfy.fail = "validation"
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.generate_image("x")
        self.assertIn("node 459:451 (UNETLoader): unet_name", str(ctx.exception))
        FakeComfy.fail = "execution"
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.generate_image("x")
        self.assertIn("node 459:458 (KSampler): CUDA out of memory", str(ctx.exception))

    def test_video(self):
        frame = self._images(1)[0]
        out = self.provider.generate_video("Lou walks out into the rain", frame, aspect_ratio="9:16", duration=6)
        graph = FakeComfy.prompts[0]
        self.assertEqual(graph["115"]["inputs"]["aspect_ratio"], "9:16 (Portrait Widescreen)")
        self.assertEqual(graph["105:111"]["inputs"]["value"], 6.0)
        self.assertEqual(len(FakeComfy.uploads), 1)
        video = out["video"]
        self.assertEqual(video["content_type"], "video/mp4")
        self.assertTrue(Path(video["local_path"]).exists() and video["local_path"].endswith(".mp4"))

    def test_video_default_duration(self):
        self.provider.generate_video("x", self._images(1)[0], aspect_ratio="16:9")
        self.assertEqual(FakeComfy.prompts[0]["105:111"]["inputs"]["value"], float(VSPEC["default_duration"]))

    def test_separate_servers(self):
        p = comfyui.ComfyUIProvider(base_url="http://image-pod", video_url="http://video-pod")
        self.assertEqual(p.urls, {"image": "http://image-pod", "video": "http://video-pod"})

    def test_unreachable_server(self):
        with self.assertRaises(RuntimeError) as ctx:
            comfyui.ComfyUIProvider(base_url="http://127.0.0.1:9").generate_image("x")
        self.assertIn("Could not reach the image ComfyUI", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
