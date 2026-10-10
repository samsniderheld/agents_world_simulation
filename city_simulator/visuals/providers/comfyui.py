"""Images and video on ComfyUI servers -- images on COMFYUI_IMAGE_URL, video
on COMFYUI_VIDEO_URL (both default to COMFYUI_URL), e.g. RunPod pods set up
with deploy/runpod-comfyui/ -- by running an API-format workflow (ComfyUI's
"Export (API)") filled in for each call. config.yaml's `comfyui` section
says which workflow each kind runs and where its prompt, seed, size, aspect
ratio, duration and output are.

A call:
1. uploads each input image (POST /upload/image), named by a hash of its
   bytes so the same picture is stored once;
2. builds the graph (prepare_graph): one LoadImage per image, wired into
   every image input of the workflow (numbered ones grown or shrunk to fit),
   the prompt, a fresh seed and the other settings filled in, nodes that
   don't feed the output dropped;
3. queues it (POST /prompt), polls GET /history/<id> until it's done, and
   downloads the output node's files (GET /view).
"""

import copy
import hashlib
import json
import math
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
# The Video node's options: (type, min, max). Anything else passes through as
# text (sampler/scheduler names; ComfyUI rejects unknown ones by name).
VIDEO_OPTIONS = {"duration": (float, 1, 20), "megapixels": (float, 0.1, 4.0), "steps": (int, 1, 100)}
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


def canvas_size(aspect_ratio: str, budget: int) -> tuple:
    """(width, height) for an aspect ratio ("16:9") with about budget x budget
    pixels, both multiples of 32 -- 16:9 at 1024 is 1376 x 768."""
    try:
        w, h = (float(x) for x in (aspect_ratio or "1:1").split(":"))
    except ValueError:
        w, h = 1.0, 1.0
    width = math.sqrt(budget * budget * w / h)
    height = budget * budget / width
    return (max(32, int(round(width / 32)) * 32), max(32, int(round(height / 32)) * 32))


def prepare_graph(template: dict, spec: dict, prompt: str, image_names: list, seed: int,
                  size: tuple = None, resolution: int = None, settings: dict = None) -> dict:
    """The workflow filled in for one call (pure: no I/O). `image_names` are
    images already uploaded to ComfyUI's input folder; `size` is the canvas
    (width, height), `resolution` the reference images' pixel budget, and
    `settings` any other {"<node id>.<input>": value} to set."""
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

    for path, value in (spec.get("set") or {}).items():     # fixed overrides, e.g. another model file
        put(path, value)
    for path in spec.get("prompt") or []:
        put(path, prompt)
    for path in spec.get("seed") or []:
        put(path, seed)
    if size and spec.get("size") in graph:
        graph[spec["size"]]["inputs"].update(width=int(size[0]), height=int(size[1]))
    if resolution and spec.get("resolution"):
        put(spec["resolution"], int(resolution))
    if image_names:
        for path, value in (spec.get("with_images") or {}).items():
            put(path, prompt if value == "{prompt}" else value)
    else:
        for path, value in (spec.get("without_images") or {}).items():
            put(path, prompt if value == "{prompt}" else value)
    for path, value in (settings or {}).items():
        put(path, value)

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
    """`base_url` (tests) points both kinds at one server; `video_url`
    overrides it for video."""

    def __init__(self, base_url: str = None, session: requests.Session = None, video_url: str = None):
        self._fixed = {}
        if base_url:
            self._fixed = {"image": base_url.rstrip("/"), "video": (video_url or base_url).rstrip("/")}
        elif video_url:
            self._fixed = {"video": video_url.rstrip("/")}
        self._session = session or requests.Session()

    @property
    def urls(self) -> dict:
        """Each kind's server: fixed at construction (tests), else the current
        defaults (config -- a node's "make default" changes them live)."""
        return {"image": self._fixed.get("image") or config.COMFYUI_IMAGE_URL,
                "video": self._fixed.get("video") or config.COMFYUI_VIDEO_URL}

    @property
    def base_url(self) -> str:
        return self.urls["image"]

    # --- the workflow -----------------------------------------------------------------
    @staticmethod
    def _spec(kind: str) -> dict:
        spec = config.COMFYUI.get(f"{kind}_workflow")
        if not spec or not spec.get("file"):
            raise RuntimeError(f"no ComfyUI {kind} workflow configured (visuals/data/config.yaml, comfyui.{kind}_workflow)")
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
    def _call(self, kind: str, method: str, path: str, url: str = None, **kw):
        url = url or self.urls[kind]
        try:
            return self._session.request(method, f"{url}{path}", timeout=kw.pop("timeout", 60), **kw)
        except requests.RequestException as e:
            env = "COMFYUI_IMAGE_URL" if kind == "image" else "COMFYUI_VIDEO_URL"
            raise RuntimeError(f"Could not reach the {kind} ComfyUI at {url} ({type(e).__name__}). Is the pod "
                               f"running and ComfyUI up (deploy/runpod-comfyui/start.sh)? It's {env} (or "
                               "COMFYUI_URL) in .env.") from e

    def _upload(self, kind: str, image_path: str, url: str = None) -> str:
        data = Path(image_path).read_bytes()
        name = hashlib.sha1(data).hexdigest()[:20] + (Path(image_path).suffix or ".png")
        resp = self._call(kind, "POST", "/upload/image", url=url,
                          files={"image": (name, data, mimetypes.guess_type(name)[0] or "image/png")},
                          data={"type": "input", "subfolder": UPLOAD_SUBFOLDER, "overwrite": "true"})
        if resp.status_code >= 400:
            raise RuntimeError(f"ComfyUI rejected an image upload ({resp.status_code}): {resp.text[:300]}")
        info = resp.json()
        return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]

    def _run(self, kind: str, spec: dict, graph: dict, url: str = None) -> list:
        """Queue `graph`, wait for it, and download the output node's files:
        [(filename, bytes, content_type)]."""
        resp = self._call(kind, "POST", "/prompt", url=url, json={"prompt": graph, "client_id": uuid.uuid4().hex})
        if resp.status_code >= 400:
            raise RuntimeError("ComfyUI refused the workflow: " + _describe_error(resp))
        prompt_id = resp.json()["prompt_id"]
        timeout = float(spec.get("timeout_seconds") or config.COMFYUI.get("timeout_seconds", 900))
        deadline = time.monotonic() + timeout
        entry = None
        while time.monotonic() < deadline:
            resp = self._call(kind, "GET", f"/history/{prompt_id}", url=url)
            entry = (resp.json() or {}).get(prompt_id) if resp.status_code < 400 else None
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI failed running the workflow: " + _execution_error(status))
                if status.get("completed", True):
                    break
            entry = None
            time.sleep(float(config.COMFYUI.get("poll_interval_seconds", 1)))
        if entry is None:
            raise TimeoutError(f"ComfyUI job {prompt_id} didn't finish within {timeout:.0f}s")
        files = _output_files((entry.get("outputs") or {}).get(spec["output"], {}))
        if not files:
            raise RuntimeError(f"ComfyUI finished, but output node {spec['output']!r} produced nothing")
        results = []
        for f in files:
            r = self._call(kind, "GET", "/view", url=url, timeout=300, params={
                "filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
            if r.status_code >= 400:
                raise RuntimeError(f"couldn't download {f['filename']} from ComfyUI ({r.status_code})")
            content_type = r.headers.get("Content-Type", "").split(";")[0].strip() \
                or mimetypes.guess_type(f["filename"])[0] or "application/octet-stream"
            results.append((f["filename"], r.content, content_type))
        return results

    @staticmethod
    def _save(filename: str, data: bytes, content_type: str):
        return storage.save_bytes(data, config.OUTPUTS_DIR, content_type=content_type, fallback_name=filename)

    # --- the Provider interface ---------------------------------------------------------------
    def generate_image(self, prompt: str, image_paths: list = None, **options) -> dict:
        spec = self._spec("image")
        template = self._template(spec)
        paths = list(image_paths or [])[:int(spec.get("max_images", 4))]
        url = normalize_url(options.pop("server_url", None))      # a node's own ComfyUI URL
        names = [self._upload("image", p, url) for p in paths]
        seed = options.get("seed")
        if seed is None:
            seed = random.randint(0, 2**48)
        # The Image node's aspect ratio and resolution (1K / 2K) set the canvas
        # and the reference images' pixel budget; explicit width/height win.
        budgets = spec.get("resolutions") or {"1K": 1024, "2K": 2048}
        budget = int(budgets.get(str(options.get("resolution") or "1K").upper(), budgets.get("1K", 1024)))
        size = canvas_size(options.get("aspect_ratio") or "1:1", budget)
        if options.get("width") and options.get("height"):
            size = (int(options["width"]), int(options["height"]))
        graph = prepare_graph(template, spec, prompt, names, seed, size, resolution=budget)
        images = []
        for filename, data, content_type in self._run("image", spec, graph, url):
            local_path = self._save(filename, data, content_type)
            width = height = None
            try:
                from PIL import Image
                with Image.open(local_path) as im:
                    width, height = im.size
            except Exception:
                pass
            images.append({"local_path": str(local_path), "url": storage.relative_path(local_path),
                           "width": width, "height": height, "content_type": content_type})
        return {"images": images, "description": "", "seed": seed}

    def generate_video(self, prompt: str, image_path: str, **options) -> dict:
        """Animate `image_path` (the workflow's first frame). The Video node's
        aspect ratio and duration (seconds) go where the workflow says."""
        spec = self._spec("video")
        template = self._template(spec)
        url = normalize_url(options.pop("server_url", None))      # a node's own ComfyUI URL
        names = [self._upload("video", image_path, url)] if image_path else []
        seed = options.get("seed")
        if seed is None:
            seed = random.randint(0, 2**48)
        settings = {}
        aspect = (spec.get("aspect_ratios") or {}).get(options.get("aspect_ratio") or "")
        if spec.get("aspect_ratio") and aspect:
            settings[spec["aspect_ratio"]] = aspect
        defaults = spec.get("defaults") or {}
        for name, path in (spec.get("options") or {}).items():
            value = options.get(name)
            if value in (None, ""):
                value = defaults.get(name)
            if value in (None, ""):
                continue                          # the workflow's own value stands
            settings[path] = _video_option(name, value)
        graph = prepare_graph(template, spec, prompt, names, int(seed), settings=settings)
        filename, data, content_type = self._run("video", spec, graph, url)[0]
        local_path = self._save(filename, data, content_type)
        return {"video": {"local_path": str(local_path), "url": storage.relative_path(local_path),
                          "content_type": content_type, "file_size": len(data)}, "seed": seed}


def normalize_url(url):
    """A ComfyUI address as typed on a node -> its base URL, or None if
    blank. Pasting an endpoint (".../prompt") works too."""
    url = (url or "").strip()
    if not url:
        return None
    if not re.match(r"^https?://[^/\s]+", url):
        raise ValueError(f"{url!r} isn't a ComfyUI address -- it should look like https://<pod id>-8188.proxy.runpod.net")
    url = url.rstrip("/")
    for suffix in ("/prompt", "/system_stats", "/api"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def check_server(kind: str, url: str = None, session: requests.Session = None) -> dict:
    """Is ComfyUI at `url` (default: that kind's) up, and does it have every
    node and model file the kind's workflow uses? {"ok", "url", "version",
    "gpu", "missing_nodes", "missing_models", "error"}."""
    session = session or requests.Session()
    url = normalize_url(url) or ComfyUIProvider().urls[kind]
    out = {"ok": False, "url": url, "version": None, "gpu": None, "missing_nodes": [], "missing_models": [],
           "error": None}
    try:
        stats = session.get(f"{url}/system_stats", timeout=15)
        if stats.status_code >= 400:
            out["error"] = f"no ComfyUI answering at {url} (HTTP {stats.status_code}) -- is the pod running?"
            return out
        info = stats.json()
        out["version"] = (info.get("system") or {}).get("comfyui_version")
        devices = info.get("devices") or []
        if devices:
            # "cuda:0 NVIDIA A100-SXM4-80GB : cudaMallocAsync" -> "NVIDIA A100-SXM4-80GB"
            name = re.sub(r"^\w+:\d+\s+", "", devices[0].get("name", "").split(" : ")[0]).strip()
            out["gpu"] = f"{name} ({round(devices[0].get('vram_total', 0) / 2**30)} GB)"
        spec = ComfyUIProvider._spec(kind)
        template = ComfyUIProvider._template(spec)
        for class_type in sorted({n["class_type"] for n in template.values() if n.get("class_type")}):
            r = session.get(f"{url}/object_info/{class_type}", timeout=15)
            node_info = (r.json() or {}).get(class_type) if r.status_code < 400 else None
            if not node_info:
                out["missing_nodes"].append(class_type)
                continue
            # model files: every "*_name" input the workflow sets must be one the server lists
            inputs = {**(node_info.get("input", {}).get("required") or {}),
                      **(node_info.get("input", {}).get("optional") or {})}
            for node in template.values():
                if node.get("class_type") != class_type:
                    continue
                for name, value in node.get("inputs", {}).items():
                    if not (name.endswith("_name") and isinstance(value, str) and name in inputs):
                        continue
                    choices = inputs[name][0] if inputs[name] else None
                    if not isinstance(choices, list):        # newer servers: ["COMBO", {"options": [...]}]
                        choices = (inputs[name][1] or {}).get("options") if len(inputs[name]) > 1 else None
                    if isinstance(choices, list) and value not in choices and value not in out["missing_models"]:
                        out["missing_models"].append(value)
    except requests.RequestException as e:
        out["error"] = f"couldn't reach {url} ({type(e).__name__}) -- is the pod running?"
        return out
    except (RuntimeError, ValueError) as e:
        out["error"] = str(e)
        return out
    out["ok"] = not out["missing_nodes"] and not out["missing_models"]
    return out


def _video_option(name: str, value):
    """A Video node option, as the workflow input wants it -- numbers typed
    and kept in range."""
    if name not in VIDEO_OPTIONS:
        return str(value)
    kind, low, high = VIDEO_OPTIONS[name]
    try:
        number = kind(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"video option {name} should be a number, not {value!r}")
    return max(low, min(high, number))


def _output_files(output: dict) -> list:
    """The files an output node reported. ComfyUI lists them under "images"
    (Save Image, and Save Video too), or "videos"/"gifs"/"audio" for others."""
    files = []
    for key in ("images", "videos", "gifs", "audio"):
        files += [f for f in output.get(key) or [] if isinstance(f, dict) and f.get("filename")]
    return files


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
