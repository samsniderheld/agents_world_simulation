"""Flask blueprint for media generation (/api/visuals/*) -- thin view functions that
parse the request and delegate to jobs.py/storage.py.
"""

from flask import Blueprint, request, send_from_directory

from jsonutil import json_response

from . import config, jobs, providers, storage

bp = Blueprint("visuals", __name__, url_prefix="/api/visuals")


@bp.get("/providers")
def providers_list():
    return json_response({
        "available": providers.AVAILABLE_PROVIDERS,
        "current": config.PROVIDER,
        # what an Image / Video node uses when it doesn't pick a provider
        "defaults": {"image": providers.default_for("image"), "video": providers.default_for("video")},
        # the ComfyUI servers a node uses when it doesn't name one
        "comfyui_urls": {"image": config.COMFYUI_IMAGE_URL, "video": config.COMFYUI_VIDEO_URL},
        "capabilities": providers.CAPABILITIES,
    })


@bp.post("/provider")
def set_provider():
    body = request.get_json(silent=True) or {}
    name = body.get("provider")
    if name not in providers.AVAILABLE_PROVIDERS:
        return json_response({"ok": False, "error": f"unknown provider {name!r}"}, status=400)
    try:
        # Constructing (and, for "local", importing torch/diffusers) here
        # means a missing dependency or unavailable backend surfaces right
        # away, in response to picking it, rather than on the next generate
        # call.
        providers.get_provider(name)
    except ImportError as e:
        return json_response({
            "ok": False,
            "error": f"'{name}' provider isn't installed ({e}). "
                     f"Run: pip install -r requirements-local-visuals.txt",
        }, status=500)
    except Exception as e:
        return json_response({"ok": False, "error": str(e)}, status=500)
    config.PROVIDER = name
    return json_response({"ok": True, "provider": name})


@bp.post("/comfyui/check")
def comfyui_check():
    """Test a ComfyUI address from a node: is it up, and does it have the
    kind's workflow nodes and model files? (body: {kind, url}; url blank =
    that kind's default)"""
    from .providers.comfyui import check_server
    body = request.get_json(silent=True) or {}
    kind = body.get("kind") if body.get("kind") in ("image", "video") else "image"
    try:
        return json_response(check_server(kind, body.get("url")))
    except ValueError as e:
        return json_response({"ok": False, "error": str(e)}, status=400)


@bp.post("/comfyui/default")
def comfyui_default():
    """Make a node's ComfyUI address the default for its kind (saved, used
    by every node without its own); a blank url goes back to .env's."""
    from .providers.comfyui import normalize_url
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in ("image", "video"):
        return json_response({"ok": False, "error": "kind must be image or video"}, status=400)
    try:
        url = normalize_url(body.get("url"))
    except ValueError as e:
        return json_response({"ok": False, "error": str(e)}, status=400)
    config.save_comfyui_default(kind, url)
    return json_response({"ok": True, "comfyui_urls": {"image": config.COMFYUI_IMAGE_URL, "video": config.COMFYUI_VIDEO_URL}})


@bp.get("/status")
def status():
    return json_response(jobs.get_status())


@bp.get("/result")
def result():
    r = jobs.get_result()
    if r is None:
        return json_response({"error": "nothing generated yet"}, status=404)
    return json_response(r)


@bp.get("/files/<path:filename>")
def files(filename):
    return send_from_directory(config.UPLOADS_DIR.parent, filename)


@bp.post("/upload")
def upload():
    # "image" for backward compatibility with the image-upload fields
    # already using it; "file" is the generic name newer callers (e.g. the
    # video-to-video upload) use, since this endpoint accepts any media
    # type -- storage.save_upload() picks the extension from content-type.
    file_storage = request.files.get("file") or request.files.get("image")
    if file_storage is None:
        return json_response({"ok": False, "error": "no file in request"}, status=400)
    path = storage.save_upload(file_storage)
    return json_response({"ok": True, "path": str(path), "url": storage.relative_path(path)})


def _style_prompt(body: dict) -> str:
    """Merges a node's own prompt with a connected Style node's
    style_prompt -- joined server-side (per the design spec: "never
    string-concatenated in the UI") so multiple Style nodes feeding one
    port, or a future change to how they're joined, only ever needs
    changing here.

    Deliberately NOT forwarding `negative_prompt`/`style_strength` to the
    provider: the active fal models (see data/config.yaml -- Gemini 3 Pro
    Image Preview / Gemini Omni Flash) are natural-language-prompted, not
    classic diffusion models, and neither exposes a verified negative-
    prompt or CFG-strength-style parameter. Sending unverified fields to
    fal's API risks a hard failure on every generation, which is worse
    than the field being a no-op -- StyleRef still captures both (see
    visuals/styles.py) for a future provider that can actually honor them.
    """
    prompt = body.get("prompt", "")
    style_prompt = body.get("style_prompt")
    return ", ".join(p for p in (prompt, style_prompt) if p)


def _style_reference_images(body: dict) -> list:
    """Style reference images are a distinct concept from `image_paths`
    (which means "edit/animate this exact image" -- a Frame's edit and a
    Video's source frame depend on that meaning) -- so they're merged into the same
    image_paths list the edit model already accepts, rather than
    replacing or renaming that field."""
    return list(body.get("image_paths") or []) + list(body.get("style_reference_images") or [])


@bp.post("/generate-image")
def generate_image():
    body = request.get_json(silent=True) or {}
    image_paths = _style_reference_images(body)
    params = {
        "prompt": _style_prompt(body),
        "image_paths": image_paths or None,
        "options": body.get("options") or {},
        "provider": body.get("provider") or None,   # the node's pick; None = the default
        "comfyui_url": body.get("comfyui_url") or None,   # the node's own ComfyUI address
    }
    ok, error = jobs.start("image", params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.post("/generate-video")
def generate_video():
    body = request.get_json(silent=True) or {}
    params = {
        "prompt": _style_prompt(body),
        "image_path": body.get("image_path"),
        "options": body.get("options") or {},
        "provider": body.get("provider") or None,   # the node's pick; None = the default
        "comfyui_url": body.get("comfyui_url") or None,   # the node's own ComfyUI address
    }
    ok, error = jobs.start("video", params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.post("/generate-video-from-reference")
def generate_video_from_reference():
    body = request.get_json(silent=True) or {}
    params = {
        "prompt": body.get("prompt", ""),
        "video_path": body.get("video_path"),
        "image_paths": body.get("image_paths") or None,
        "options": body.get("options") or {},
        "provider": body.get("provider") or None,   # the node's pick; None = the default
        "comfyui_url": body.get("comfyui_url") or None,   # the node's own ComfyUI address
    }
    ok, error = jobs.start("video_reference", params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.post("/generate-music")
def generate_music():
    body = request.get_json(silent=True) or {}
    params = {
        "prompt": body.get("prompt", ""),
        "options": body.get("options") or {},
    }
    ok, error = jobs.start("music", params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)
