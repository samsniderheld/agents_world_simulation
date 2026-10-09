"""Image generation on a ComfyUI server (COMFYUI_URL) -- e.g. a RunPod pod
set up with deploy/runpod-comfyui/ -- by running an API-format workflow
(ComfyUI's "Export (API)") filled in for each call. config.yaml's `comfyui`
section says which workflow and where its prompt, seed, size and output are.

A call:
1. uploads each input image (POST /upload/image), named by a hash of its
   bytes so the same portrait is stored once;
2. builds the graph (prepare_graph): one LoadImage per image, wired into
   every numbered image input of the workflow (grown or shrunk to fit), the
   prompt, a fresh seed and the latent size set, nodes that don't feed the
   output dropped;
3. queues it (POST /prompt), polls GET /history/<id> until it's done, and
   downloads the output node's images (GET /view).
"""

import copy
import hashlib
import json
import mimetypes
import random
import re
import time
import uuid
from pathlib import Path

import requests

from .. import config, storage
from .base import Provider

_NUMBERED = re.compile(r"^(.*?)(\d+)$")      # "images.image_2" -> ("images.image_", "2")
UPLOAD_SUBFOLDER = "city_simulator"


def _is_link(value) -> bool:
    """A node input wired to another node's output: [node id, output index]."""
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int)


def _split(path: str):
    """'<node id>.<input name>' -- input names may contain dots, node ids don't."""
    node, _, name = path.partition(".")
    if not node or not name:
        raise ValueError(f"comfyui workflow setting {path!r} should look like '<node id>.<input name>'")
    return node, name


def prepare_graph(template: dict, spec: dict, prompt: str, image_names: list, seed: int,
                  size: tuple = None) -> dict:
    """The workflow filled in for one call (pure: no I/O). `image_names` are
    images already uploaded to ComfyUI's input folder."""
    graph = copy.deepcopy(template)
    placeholders = {nid for nid, n in graph.items() if n.get("class_type") == "LoadImage"}
    if image_names and not placeholders:
        raise ValueError("this workflow has no LoadImage node to feed images into")

    # Every numbered input reading a placeholder belongs to a family (node,
    # prefix) numbered from its lowest index; an un-numbered one takes image 1.
    families, singles = {}, []
    for nid, node in graph.items():
        for name, value in list(node.get("inputs", {}).items()):
            if not (_is_link(value) and value[0] in placeholders):
                continue
            del node["inputs"][name]
            m = _NUMBERED.match(name)
            if m:
                key = (nid, m.group(1))
                families[key] = min(families.get(key, int(m.group(2))), int(m.group(2)))
            else:
                singles.append((nid, name))
    for nid in placeholders:
        del graph[nid]
    loaders = []
    for i, name in enumerate(image_names):
        loader = f"cs_image_{i + 1}"
        graph[loader] = {"class_type": "LoadImage", "inputs": {"image": name},
                         "_meta": {"title": f"City Simulator image {i + 1}"}}
        loaders.append(loader)
    for (nid, prefix), start in families.items():
        for i, loader in enumerate(loaders):
            graph[nid]["inputs"][f"{prefix}{start + i}"] = [loader, 0]
    for nid, name in singles:
        if loaders:
            graph[nid]["inputs"][name] = [loaders[0], 0]

    def put(path, value):
        node, name = _split(path)
        if node not in graph:
            raise ValueError(f"comfyui workflow setting {path!r}: the workflow has no node {node!r}")
        graph[node]["inputs"][name] = value

    for path in spec.get("prompt") or []:
        put(path, prompt)
    for path in spec.get("seed") or []:
        put(path, seed)
    if size and spec.get("size") in graph:
        graph[spec["size"]]["inputs"].update(width=int(size[0]), height=int(size[1]))
    if not image_names:
        for path, value in (spec.get("without_images") or {}).items():
            put(path, prompt if value == "{prompt}" else value)

    # Keep only what the output needs.
    output = spec.get("output")
    if output not in graph:
        raise ValueError(f"comfyui workflow: output node {output!r} isn't in the workflow")
    keep, stack = set(), [output]
    while stack:
        nid = stack.pop()
        if nid in keep or nid not in graph:
            continue
        keep.add(nid)
        stack.extend(v[0] for v in graph[nid].get("inputs", {}).values() if _is_link(v))
    graph = {nid: node for nid, node in graph.items() if nid in keep}
    if not image_names and any(nid in graph for nid, _ in singles):
        raise ValueError("this workflow needs an input image (its image input isn't numbered, so it can't run without one)")
    return graph


class ComfyUIProvider(Provider):
    def __init__(self, base_url: str = None, session: requests.Session = None):
        self.base_url = (base_url or config.COMFYUI_URL).rstrip("/")
        self._session = session or requests.Session()

    # --- the workflow -----------------------------------------------------------------
    @staticmethod
    def _spec() -> dict:
        spec = config.COMFYUI.get("image_workflow")
        if not spec or not spec.get("file"):
            raise RuntimeError("no ComfyUI workflow configured (visuals/data/config.yaml, comfyui.image_workflow)")
        return spec

    @staticmethod
    def _template(spec: dict) -> dict:
        path = Path(config.COMFYUI_DIR) / spec["file"]
        if not path.exists():
            raise RuntimeError(f"ComfyUI workflow file not found: {path}")
        graph = json.loads(path.read_text())
        if "nodes" in graph and "links" in graph:
            raise RuntimeError(f"{path.name} is a UI-format workflow -- export it with ComfyUI's \"Export (API)\"")
        return graph

    # --- the server -------------------------------------------------------------------------
    def _call(self, method: str, path: str, **kw):
        try:
            return self._session.request(method, f"{self.base_url}{path}", timeout=kw.pop("timeout", 60), **kw)
        except requests.RequestException as e:
            raise RuntimeError(f"Could not reach ComfyUI at {self.base_url} ({type(e).__name__}). Is the pod "
                               "running and ComfyUI started (deploy/runpod-comfyui/start.sh)? COMFYUI_URL is in .env.") from e

    def _upload(self, image_path: str) -> str:
        data = Path(image_path).read_bytes()
        name = hashlib.sha1(data).hexdigest()[:20] + (Path(image_path).suffix or ".png")
        resp = self._call("POST", "/upload/image",
                          files={"image": (name, data, mimetypes.guess_type(name)[0] or "image/png")},
                          data={"type": "input", "subfolder": UPLOAD_SUBFOLDER, "overwrite": "true"})
        if resp.status_code >= 400:
            raise RuntimeError(f"ComfyUI rejected an image upload ({resp.status_code}): {resp.text[:300]}")
        info = resp.json()
        return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]

    def _queue(self, graph: dict) -> str:
        resp = self._call("POST", "/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex})
        if resp.status_code >= 400:
            raise RuntimeError("ComfyUI refused the workflow: " + _describe_error(resp))
        return resp.json()["prompt_id"]

    def _wait(self, prompt_id: str) -> dict:
        timeout = float(config.COMFYUI.get("timeout_seconds", 900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = self._call("GET", f"/history/{prompt_id}")
            entry = (resp.json() or {}).get(prompt_id) if resp.status_code < 400 else None
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI failed running the workflow: " + _execution_error(status))
                if status.get("completed", True):
                    return entry
            time.sleep(float(config.COMFYUI.get("poll_interval_seconds", 1)))
        raise TimeoutError(f"ComfyUI job {prompt_id} didn't finish within {timeout:.0f}s")

    def _download(self, image: dict) -> dict:
        resp = self._call("GET", "/view", timeout=120, params={
            "filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
        if resp.status_code >= 400:
            raise RuntimeError(f"couldn't download {image['filename']} from ComfyUI ({resp.status_code})")
        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip() or "image/png"
        local_path = storage.save_bytes(resp.content, config.OUTPUTS_DIR, content_type=content_type,
                                        fallback_name=image["filename"])
        width = height = None
        try:
            from PIL import Image
            with Image.open(local_path) as im:
                width, height = im.size
        except Exception:
            pass
        return {"local_path": str(local_path), "url": storage.relative_path(local_path),
                "width": width, "height": height, "content_type": content_type}

    # --- the Provider interface ---------------------------------------------------------------
    def generate_image(self, prompt: str, image_paths: list = None, **options) -> dict:
        spec = self._spec()
        template = self._template(spec)
        paths = list(image_paths or [])[:int(spec.get("max_images", 4))]
        names = [self._upload(p) for p in paths]
        seed = options.get("seed")
        if seed is None:
            seed = random.randint(0, 2**48)
        sizes = spec.get("sizes") or {}
        size = sizes.get(options.get("aspect_ratio")) or sizes.get("1:1")
        if options.get("width") and options.get("height"):
            size = (options["width"], options["height"])
        entry = self._wait(self._queue(prepare_graph(template, spec, prompt, names, seed, size)))
        produced = (entry.get("outputs") or {}).get(spec["output"], {}).get("images", [])
        if not produced:
            raise RuntimeError(f"ComfyUI finished, but output node {spec['output']!r} produced no images")
        return {"images": [self._download(im) for im in produced], "description": "", "seed": seed}


def _describe_error(resp) -> str:
    """ComfyUI's /prompt validation error: the message plus each failing
    node's first problem."""
    try:
        data = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"
    parts = [(data.get("error") or {}).get("message") or f"HTTP {resp.status_code}"]
    for nid, info in (data.get("node_errors") or {}).items():
        errs = info.get("errors") or [{}]
        parts.append(f"node {nid} ({info.get('class_type', '?')}): {errs[0].get('details') or errs[0].get('message', '')}")
    return "; ".join(parts)


def _execution_error(status: dict) -> str:
    for kind, msg in status.get("messages") or []:
        if kind == "execution_error":
            return f"node {msg.get('node_id')} ({msg.get('node_type')}): {msg.get('exception_message', '').strip()}"
    return "unknown error"
