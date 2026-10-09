"""Image generation on ComfyUI -- a ComfyUI server, or a RunPod Serverless
endpoint running RunPod's worker-comfyui (COMFYUI_URL) -- by running an
API-format workflow -- one exported with ComfyUI's "Export (API)" -- filled
in for each call. See config.yaml's `comfyui` section for how a workflow is
described.

A call:
1. uploads each input image to the server (POST /upload/image, named by a
   hash of its bytes, so the same portrait is only stored once);
2. builds the graph (prepare_graph): one LoadImage per image, wired into
   every numbered image input of the template (grown or shrunk to fit),
   the prompt, a fresh seed and the latent size set, and every node that
   doesn't feed the output dropped;
3. queues it (POST /prompt), waits for it (GET /history/<id>), and
   downloads the output node's images (GET /view).
"""

import base64
import copy
import hashlib
import io
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


def _split(path: str):
    """'<node id>.<input name>' (input names may contain dots; node ids don't)."""
    node, _, name = path.partition(".")
    if not node or not name:
        raise ValueError(f"comfyui workflow binding {path!r} should look like '<node id>.<input name>'")
    return node, name


def _is_link(value) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int)


def prepare_graph(template: dict, spec: dict, prompt: str, image_names: list, seed: int,
                  size: tuple = None) -> dict:
    """The template workflow filled in for one call (pure: no I/O).
    `image_names` are ComfyUI input-image names, already uploaded."""
    graph = copy.deepcopy(template)
    placeholders = {nid for nid, n in graph.items() if n.get("class_type") == "LoadImage"}
    if not placeholders and image_names:
        raise ValueError("this workflow has no LoadImage node to feed images into")

    # Image inputs: every numbered input reading a placeholder belongs to a
    # family (node, prefix), numbered from its lowest index; an un-numbered
    # one ("image") takes the first image.
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
        loader_id = f"cs_image_{i + 1}"
        graph[loader_id] = {"class_type": "LoadImage", "inputs": {"image": name},
                            "_meta": {"title": f"City Simulator image {i + 1}"}}
        loaders.append(loader_id)
    for (nid, prefix), start in families.items():
        for i, loader_id in enumerate(loaders):
            graph[nid]["inputs"][f"{prefix}{start + i}"] = [loader_id, 0]
    for nid, name in singles:
        if loaders:
            graph[nid]["inputs"][name] = [loaders[0], 0]

    def put(path, value):
        node, name = _split(path)
        if node not in graph:
            raise ValueError(f"comfyui workflow binding {path!r}: no node {node!r} in the workflow")
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

    # Keep only what the output needs (drops e.g. a Compare node, and in
    # text-to-image mode the image-only branches the overrides cut off).
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
    if singles and not image_names and any(nid in graph for nid, _ in singles):
        raise ValueError("this workflow needs an input image (its image input isn't numbered, so it can't run without one)")
    return graph


class ComfyUIProvider(Provider):
    """Two ways to reach ComfyUI, picked from COMFYUI_URL:

    - a ComfyUI server (http://host:8188): images uploaded with
      /upload/image, the job queued on /prompt, polled on /history/<id>,
      results downloaded from /view;
    - a RunPod Serverless endpoint (https://api.runpod.ai/v2/<id>, as
      RunPod's worker-comfyui serves it): one POST /run carrying the
      workflow and the images as base64, polled on /status/<job id>,
      results returned inside the job's output. Needs RUNPOD_API_KEY.
    """

    def __init__(self, base_url: str = None, session: requests.Session = None, runpod: bool = None):
        url = (base_url or config.COMFYUI_URL).rstrip("/")
        endpoint = _runpod_base(url)
        self.runpod = bool(endpoint) if runpod is None else runpod
        self.base_url = endpoint or url
        self._session = session or requests.Session()

    # --- the workflow ---------------------------------------------------------------
    @staticmethod
    def _spec() -> dict:
        spec = (config.COMFYUI or {}).get("image_workflow")
        if not spec or not spec.get("file"):
            raise RuntimeError("no ComfyUI image workflow configured (visuals/data/config.yaml, comfyui.image_workflow)")
        return spec

    @staticmethod
    def _template(spec: dict) -> dict:
        path = Path(config.COMFYUI_DIR) / spec["file"]
        if not path.exists():
            raise RuntimeError(f"ComfyUI workflow file not found: {path}")
        graph = json.loads(path.read_text())
        if "nodes" in graph and "links" in graph:
            raise RuntimeError(f"{path.name} is a UI-format workflow; export it with ComfyUI's \"Export (API)\" instead")
        return graph

    @staticmethod
    def _settings() -> dict:
        return config.COMFYUI or {}

    # --- HTTP -------------------------------------------------------------------------
    def _call(self, method: str, path: str, **kw):
        headers = kw.pop("headers", {})
        if self.runpod:
            if not config.RUNPOD_API_KEY:
                raise RuntimeError("COMFYUI_URL is a RunPod Serverless endpoint: set RUNPOD_API_KEY in .env "
                                   "(RunPod console -> Settings -> API Keys)")
            headers["Authorization"] = f"Bearer {config.RUNPOD_API_KEY}"
        try:
            return self._session.request(method, f"{self.base_url}{path}", headers=headers,
                                         timeout=kw.pop("timeout", 60), **kw)
        except requests.RequestException as e:
            raise RuntimeError(f"Could not reach ComfyUI at {self.base_url} ({type(e).__name__}). "
                               "Is it running? Set COMFYUI_URL in .env if it's elsewhere.") from e

    # --- a ComfyUI server ----------------------------------------------------------------
    def _upload(self, name: str, data: bytes) -> str:
        mime = mimetypes.guess_type(name)[0] or "image/png"
        resp = self._call("POST", "/upload/image", files={"image": (name, data, mime)},
                          data={"type": "input", "subfolder": UPLOAD_SUBFOLDER, "overwrite": "true"})
        if resp.status_code >= 400:
            raise RuntimeError(f"ComfyUI rejected an image upload ({resp.status_code}): {resp.text[:300]}")
        info = resp.json()
        return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]

    def _run_on_server(self, graph_for, images: list, output: str) -> list:
        names = [self._upload(name, data) for name, data in images]
        resp = self._call("POST", "/prompt", json={"prompt": graph_for(names), "client_id": uuid.uuid4().hex})
        if resp.status_code >= 400:
            raise RuntimeError("ComfyUI refused the workflow: " + _describe_error(resp))
        prompt_id = resp.json()["prompt_id"]
        entry = self._poll(lambda: self._server_status(prompt_id), prompt_id)
        produced = (entry.get("outputs") or {}).get(output, {}).get("images", [])
        results = []
        for im in produced:
            r = self._call("GET", "/view", timeout=120, params={
                "filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": im.get("type", "output")})
            if r.status_code >= 400:
                raise RuntimeError(f"couldn't download {im['filename']} from ComfyUI ({r.status_code})")
            results.append((im["filename"], r.content, r.headers.get("Content-Type", "").split(";")[0].strip()))
        return results

    def _server_status(self, prompt_id: str):
        resp = self._call("GET", f"/history/{prompt_id}")
        entry = (resp.json() or {}).get(prompt_id) if resp.status_code < 400 else None
        if not entry:
            return None
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            raise RuntimeError("ComfyUI failed while running the workflow: " + _execution_error(status))
        return entry if status.get("completed", True) else None

    # --- a RunPod Serverless endpoint -------------------------------------------------------
    def _run_on_runpod(self, graph_for, images: list, output: str) -> list:
        images = _fit_payload(images, RUNPOD_PAYLOAD_LIMIT)
        names = [name for name, _ in images]
        payload = {"input": {"workflow": graph_for(names), "images": [
            {"name": name, "image": f"data:{mimetypes.guess_type(name)[0] or 'image/png'};base64,"
                                    + base64.b64encode(data).decode()} for name, data in images]}}
        resp = self._call("POST", "/run", json=payload, timeout=120)
        if resp.status_code == 401:
            raise RuntimeError("RunPod rejected RUNPOD_API_KEY (401) -- check the key in .env")
        if resp.status_code >= 400:
            raise RuntimeError(f"RunPod refused the job ({resp.status_code}): {resp.text[:300]}")
        job_id = resp.json()["id"]
        try:
            job = self._poll(lambda: self._runpod_status(job_id), job_id)
        except TimeoutError:
            self._call("POST", f"/cancel/{job_id}")      # don't leave a worker busy on it
            raise
        return _runpod_images(job.get("output"), self._session)

    def _runpod_status(self, job_id: str):
        resp = self._call("GET", f"/status/{job_id}")
        if resp.status_code >= 400:
            raise RuntimeError(f"RunPod status check failed ({resp.status_code}): {resp.text[:300]}")
        job = resp.json()
        state = job.get("status")
        if state == "COMPLETED":
            return job
        if state in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise RuntimeError(f"RunPod job {job_id} {state.lower()}: {_runpod_error(job)}")
        return None                                     # IN_QUEUE / IN_PROGRESS (a cold start can take minutes)

    # --- shared --------------------------------------------------------------------------
    def _poll(self, check, job_id: str):
        settings = self._settings()
        timeout = float(settings.get("timeout_seconds", 900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = check()
            if result is not None:
                return result
            time.sleep(float(settings.get("poll_interval_seconds", 1)))
        raise TimeoutError(f"ComfyUI job {job_id} didn't finish within {timeout:.0f}s")

    @staticmethod
    def _save(filename: str, data: bytes, content_type: str) -> dict:
        content_type = content_type or mimetypes.guess_type(filename)[0] or "image/png"
        local_path = storage.save_bytes(data, config.OUTPUTS_DIR, content_type=content_type, fallback_name=filename)
        width = height = None
        try:
            from PIL import Image
            with Image.open(local_path) as im:
                width, height = im.size
        except Exception:
            pass
        return {"local_path": str(local_path), "url": storage.relative_path(local_path),
                "width": width, "height": height, "content_type": content_type}

    # --- the Provider interface ----------------------------------------------------------
    def generate_image(self, prompt: str, image_paths: list = None, **options) -> dict:
        spec = self._spec()
        template = self._template(spec)
        paths = list(image_paths or [])[:int(spec.get("max_images", 4))]
        images = []
        for path in paths:      # named by content: the same picture is the same file
            data = Path(path).read_bytes()
            images.append((hashlib.sha1(data).hexdigest()[:20] + (Path(path).suffix or ".png"), data))
        seed = options.get("seed")
        if seed is None:
            seed = random.randint(0, 2**48)
        sizes = spec.get("sizes") or {}
        size = sizes.get(options.get("aspect_ratio")) or sizes.get("1:1")
        if options.get("width") and options.get("height"):
            size = (options["width"], options["height"])

        def graph_for(names):
            return prepare_graph(template, spec, prompt, names, seed, size)
        run = self._run_on_runpod if self.runpod else self._run_on_server
        produced = run(graph_for, images, spec["output"])
        if not produced:
            raise RuntimeError(f"ComfyUI finished, but output node {spec['output']!r} produced no images")
        return {"images": [self._save(*im) for im in produced], "description": "", "seed": seed,
                "dropped_images": max(0, len(image_paths or []) - len(paths))}


# RunPod caps a /run request body at 10 MB; leave room for the workflow.
RUNPOD_PAYLOAD_LIMIT = 9 * 1024 * 1024


def _runpod_base(url: str):
    """https://api.runpod.ai/v2/<endpoint id> from any URL of that endpoint
    (the /run or /runsync URL the console shows works too), else None."""
    m = re.match(r"^(https?://api\.runpod\.ai/v2/[^/?#]+)", url or "")
    return m.group(1) if m else None


def _fit_payload(images: list, limit: int) -> list:
    """The images as sent to RunPod: unchanged if they fit in `limit` as
    base64, else re-encoded as JPEG (same size, much smaller files)."""
    if sum(len(d) for _, d in images) * 4 // 3 <= limit:
        return images
    from PIL import Image
    out = []
    for name, data in images:
        buf = io.BytesIO()
        with Image.open(io.BytesIO(data)) as im:
            im.convert("RGB").save(buf, format="JPEG", quality=90)
        out.append((name.rsplit(".", 1)[0] + ".jpg", buf.getvalue()))
    if sum(len(d) for _, d in out) * 4 // 3 > limit:
        raise RuntimeError(f"{len(images)} images are too big to send to RunPod in one job (10 MB limit) "
                           "even as JPEG -- lower comfyui.image_workflow.max_images")
    return out


def _runpod_images(output, session) -> list:
    """[(filename, bytes, content_type)] from worker-comfyui's job output:
    {"images": [{"filename", "type": "base64" | "s3_url", "data"}]}, or the
    older {"message": <base64 or URL>}."""
    if isinstance(output, dict) and output.get("images"):
        items = output["images"]
    elif isinstance(output, dict) and isinstance(output.get("message"), str):
        msg = output["message"]
        items = [{"filename": "output.png", "type": "s3_url" if msg.startswith("http") else "base64", "data": msg}]
    else:
        errors = output
        if isinstance(output, dict):
            errors = output.get("errors") or output.get("error") or output
        raise RuntimeError(f"RunPod job finished without images: {str(errors)[:300]}")
    results = []
    for item in items:
        data = item.get("data") or ""
        if item.get("type") == "s3_url" or data.startswith("http"):
            r = session.get(data, timeout=120)
            r.raise_for_status()
            content = r.content
        else:
            content = base64.b64decode(data.split(",", 1)[1] if data.startswith("data:") else data)
        results.append((item.get("filename") or "output.png", content, ""))
    return results


def _runpod_error(job: dict) -> str:
    err = job.get("error")
    if not err and isinstance(job.get("output"), dict):
        err = job["output"].get("error") or job["output"].get("errors")
    if isinstance(err, str):
        try:                        # workers often put a JSON blob in the error string
            parsed = json.loads(err)
            err = parsed.get("error_message") or parsed.get("message") or err
        except ValueError:
            pass
    return str(err or "no error message")[:500]


def _describe_error(resp) -> str:
    """ComfyUI's /prompt validation error, readable: the error plus each
    failing node's first problem."""
    try:
        data = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"
    parts = [(data.get("error") or {}).get("message") or f"HTTP {resp.status_code}"]
    for nid, info in (data.get("node_errors") or {}).items():
        errs = info.get("errors") or []
        detail = errs[0].get("details") or errs[0].get("message") if errs else ""
        parts.append(f"node {nid} ({info.get('class_type', '?')}): {detail}")
    return "; ".join(p for p in parts if p)


def _execution_error(status: dict) -> str:
    for kind, msg in status.get("messages") or []:
        if kind == "execution_error":
            return f"node {msg.get('node_id')} ({msg.get('node_type')}): {msg.get('exception_message', '').strip()}"
    return "unknown error"
