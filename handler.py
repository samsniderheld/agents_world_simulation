"""The worker's entry point (start.sh runs `python -u /handler.py`).

RunPod's GitHub builder only builds a repo that contains a handler calling
runpod.serverless.start(). This image's real handler is the one RunPod's
worker-comfyui base image ships; the Dockerfile moves it aside to
/worker_comfyui_handler.py, and this file loads it and starts it -- so the
worker behaves exactly as the stock worker-comfyui does (same request and
response format, which is what the app's ComfyUI provider speaks).
"""

import importlib.util
import os
import sys

import runpod

WORKER_HANDLER = os.environ.get("WORKER_HANDLER", "/worker_comfyui_handler.py")


def load_worker_handler(path: str = WORKER_HANDLER):
    """worker-comfyui's handler module, loaded from `path` (its own imports,
    e.g. network_volume.py, live next to it)."""
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location("worker_comfyui_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    runpod.serverless.start({"handler": load_worker_handler().handler})
