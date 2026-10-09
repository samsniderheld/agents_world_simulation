"""deploy/runpod-comfyui/: the worker's handler.py exists twice -- in the
image's build folder (what the Dockerfile copies) and at the repo root (where
RunPod's GitHub builder looks for a runpod.serverless.start() handler). They
must stay identical."""

import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
BUILD = APP / "deploy" / "runpod-comfyui"


class RunpodWorker(unittest.TestCase):
    def test_handler_copies_match(self):
        root = APP.parent / "handler.py"
        self.assertTrue(root.exists(), "the repo root needs handler.py for RunPod's GitHub builder")
        self.assertEqual(root.read_text(), (BUILD / "handler.py").read_text(),
                         "handler.py at the repo root and in deploy/runpod-comfyui/ differ -- copy one over the other")

    def test_dockerfile_copies_the_handler(self):
        dockerfile = (BUILD / "Dockerfile").read_text()
        self.assertIn("COPY handler.py /handler.py", dockerfile)
        self.assertIn("runpod.serverless.start", (BUILD / "handler.py").read_text())


if __name__ == "__main__":
    unittest.main()
