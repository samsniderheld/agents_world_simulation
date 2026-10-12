"""deploy/runpod-comfyui/pods.py against a stand-in RunPod REST API: `up`
makes the network volume and the pod (with the settings' GPUs, the volume's
data center, the ports and the SSH key), waits for ComfyUI, fixes a pod
that isn't ready over SSH (restarting it after a ComfyUI update), and makes
it the app's default; `down` deletes the pod and, if asked, the volume.
Nothing here talks to RunPod."""

import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "deploy" / "runpod-comfyui"
spec = importlib.util.spec_from_file_location("pods", HERE / "pods.py")
pods = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pods)


class FakeRunPod(BaseHTTPRequestHandler):
    state = {}

    def log_message(self, *a):
        pass

    def _json(self, code, data=None):
        body = json.dumps(data).encode() if data is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        s = FakeRunPod.state
        if self.headers.get("Authorization") != "Bearer test-key" and not self.path.startswith("/comfy/"):
            return self._json(401, {"error": "unauthorized"})
        if self.path == "/pods":
            return self._json(200, list(s["pods"].values()))
        if self.path.startswith("/pods/"):
            return self._json(200, s["pods"][self.path.split("/")[2]])
        if self.path == "/networkvolumes":
            return self._json(200, list(s["volumes"].values()))
        if self.path.startswith("/comfy/") and self.path.endswith("/system_stats"):
            return self._json(200, {"system": {"comfyui_version": "0.39.2"}})
        self._json(404, {})

    def do_POST(self):
        s = FakeRunPod.state
        body = self._body()
        if self.path == "/networkvolumes":
            vol = {"id": f"vol{len(s['volumes']) + 1}", **body}
            s["volumes"][vol["id"]] = vol
            return self._json(200, vol)
        if self.path == "/pods":
            s["created"].append(body)
            pod = {"id": f"pod{len(s['created'])}", "name": body["name"], "desiredStatus": "RUNNING",
                   "publicIp": "203.0.113.7", "portMappings": {"22": 40022}, "costPerHr": 0.79}
            s["pods"][pod["id"]] = pod
            return self._json(201, pod)
        pod_id, action = self.path.split("/")[2], self.path.split("/")[3]
        s["actions"].append((action, pod_id))
        if action == "start":
            s["pods"][pod_id]["desiredStatus"] = "RUNNING"
        return self._json(200, s["pods"][pod_id])

    def do_DELETE(self):
        s = FakeRunPod.state
        kind, item = self.path.split("/")[1], self.path.split("/")[2]
        (s["pods"] if kind == "pods" else s["volumes"]).pop(item)
        s["actions"].append(("delete", item))
        self._json(204)


class Pods(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRunPod)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeRunPod.state = {"pods": {}, "volumes": {}, "created": [], "actions": []}
        self.api = pods.RunPod("test-key", base_url=self.base)
        self.settings = {**pods.load_settings(), "comfyui_url": self.base + "/comfy/{pod_id}"}
        self.defaults = []
        self.patches = [mock.patch.object(pods.time, "sleep", lambda s: None),
                        mock.patch.object(pods, "say", lambda *a, **k: None),
                        mock.patch.object(pods, "set_app_default", lambda kind, url: self.defaults.append((kind, url))),
                        mock.patch.object(pods, "ssh_public_key", lambda: "ssh-ed25519 AAAA test")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_up_creates_volume_and_pod(self):
        with mock.patch.object(pods, "check", return_value={"ok": True, "version": "0.39.2", "gpu": "L40S"}):
            pods.up(self.api, self.settings, "image")
        vol = next(iter(FakeRunPod.state["volumes"].values()))
        self.assertEqual((vol["name"], vol["size"], vol["dataCenterId"]),
                         ("city-sim-comfyui-image", self.settings["image"]["volume_gb"], self.settings["datacenter"]))
        body = FakeRunPod.state["created"][0]
        self.assertEqual(body["gpuTypeIds"], self.settings["image"]["gpus"])
        self.assertEqual(body["networkVolumeId"], vol["id"])
        self.assertEqual(body["dataCenterIds"], [vol["dataCenterId"]])     # a pod must sit with its volume
        self.assertIn("8188/http", body["ports"])
        self.assertEqual(body["env"]["PUBLIC_KEY"], "ssh-ed25519 AAAA test")
        self.assertEqual(self.defaults, [("image", self.base + "/comfy/pod1")])

    def test_up_reuses_a_running_pod_and_starts_a_stopped_one(self):
        FakeRunPod.state["volumes"]["v"] = {"id": "v", "name": "city-sim-comfyui-video", "dataCenterId": "EU-RO-1"}
        FakeRunPod.state["pods"]["p9"] = {"id": "p9", "name": "city-sim-comfyui-video", "desiredStatus": "EXITED"}
        with mock.patch.object(pods, "check", return_value={"ok": True}):
            pods.up(self.api, self.settings, "video")
        self.assertEqual(FakeRunPod.state["created"], [])
        self.assertIn(("start", "p9"), FakeRunPod.state["actions"])

    def test_up_finishes_setup_over_ssh_and_restarts_after_an_update(self):
        results = iter([{"ok": False, "missing_nodes": ["QwenImage21Cache"], "missing_models": ["x.safetensors"]},
                        {"ok": True}])
        with mock.patch.object(pods, "check", side_effect=lambda kind, url: next(results)), \
                mock.patch.object(pods, "run_setup_over_ssh", return_value=3) as ssh:
            pods.up(self.api, self.settings, "image")
        self.assertEqual(ssh.call_args[0][1], "image")
        self.assertIn(("restart", "pod1"), FakeRunPod.state["actions"])
        self.assertEqual(len(self.defaults), 1)

    def test_up_without_ssh_says_what_to_do(self):
        with mock.patch.object(pods, "check", return_value={"ok": False, "missing_models": ["x"]}), \
                mock.patch.object(pods, "run_setup_over_ssh", return_value=None), self.assertRaises(SystemExit):
            pods.up(self.api, self.settings, "video")
        self.assertEqual(self.defaults, [])

    def test_up_all_launches_both_before_waiting(self):
        order = []
        real_wait = pods.wait_for_comfyui

        def wait(url, minutes=30):
            order.append(("wait", url.rsplit("/", 1)[1], len(FakeRunPod.state["created"])))
            return real_wait(url, minutes)
        with mock.patch.object(pods, "check", return_value={"ok": True}), \
                mock.patch.object(pods, "wait_for_comfyui", side_effect=wait):
            results = pods.up_many(self.api, self.settings, pods.KINDS)
        self.assertEqual([b["name"] for b in FakeRunPod.state["created"]],
                         ["city-sim-comfyui-image", "city-sim-comfyui-video"])
        self.assertEqual([o[2] for o in order], [2, 2])            # both pods existed before the first wait
        self.assertEqual(set(results), {"image", "video"})
        self.assertEqual([k for k, _ in self.defaults], ["image", "video"])

    def test_up_all_carries_on_past_a_failure(self):
        def check(kind, url):
            return {"ok": True} if kind == "video" else {"ok": False, "missing_models": ["x"]}
        with mock.patch.object(pods, "check", side_effect=check), \
                mock.patch.object(pods, "run_setup_over_ssh", return_value=None):
            results = pods.up_many(self.api, self.settings, pods.KINDS)
        self.assertIsInstance(results["video"], dict)
        self.assertIsInstance(results["image"], str)                # the failure, reported
        self.assertEqual([k for k, _ in self.defaults], ["video"])

    def test_up_with_no_kind_means_all(self):
        with mock.patch.object(pods, "RunPod", return_value=self.api), \
                mock.patch.object(pods, "load_settings", return_value=self.settings), \
                mock.patch.object(pods, "up_many", return_value={"image": {}, "video": {}}) as many:
            pods.main(["up"])
        self.assertEqual(many.call_args[0][2], pods.KINDS)

    def test_down_keeps_the_volume_unless_asked(self):
        FakeRunPod.state["volumes"]["v"] = {"id": "v", "name": "city-sim-comfyui-image", "size": 60}
        FakeRunPod.state["pods"]["p1"] = {"id": "p1", "name": "city-sim-comfyui-image", "desiredStatus": "RUNNING"}
        pods.down(self.api, "image")
        self.assertEqual(FakeRunPod.state["actions"], [("delete", "p1")])
        self.assertIn("v", FakeRunPod.state["volumes"])
        pods.down(self.api, "image", volume=True, yes=True)
        self.assertNotIn("v", FakeRunPod.state["volumes"])

    def test_bad_key(self):
        with self.assertRaises(SystemExit):
            pods.RunPod("wrong", base_url=self.base).pods()

    def test_key_without_permission_says_so(self):
        with mock.patch.object(pods.requests.Session, "request",
                               return_value=mock.Mock(status_code=403, content=b"", text="")), \
                self.assertRaises(SystemExit) as ctx:
            self.api.volumes()
        self.assertIn("doesn't have permission", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
