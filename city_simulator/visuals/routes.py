"""Flask blueprint for the Visuals tab's API -- thin view functions that
parse the request and delegate to jobs.py/storage.py.
"""

from flask import Blueprint, request, send_from_directory

from jsonutil import json_response

from . import config, jobs, providers, storage

bp = Blueprint("visuals", __name__, url_prefix="/api/visuals")


@bp.get("/providers")
def providers_list():
    return json_response({"available": providers.AVAILABLE_PROVIDERS, "current": config.PROVIDER})


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
    file_storage = request.files.get("image")
    if file_storage is None:
        return json_response({"ok": False, "error": "no 'image' file in request"}, status=400)
    path = storage.save_upload(file_storage)
    return json_response({"ok": True, "path": str(path), "url": storage.relative_path(path)})


@bp.post("/generate-image")
def generate_image():
    body = request.get_json(silent=True) or {}
    params = {
        "prompt": body.get("prompt", ""),
        "image_paths": body.get("image_paths") or None,
        "options": body.get("options") or {},
    }
    ok, error = jobs.start("image", params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.post("/generate-video")
def generate_video():
    body = request.get_json(silent=True) or {}
    params = {
        "prompt": body.get("prompt", ""),
        "image_path": body.get("image_path"),
        "options": body.get("options") or {},
    }
    ok, error = jobs.start("video", params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)
