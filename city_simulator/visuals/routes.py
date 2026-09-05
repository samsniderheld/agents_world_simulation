"""Flask blueprint for the Visuals tab's API -- thin view functions that
parse the request and delegate to jobs.py/storage.py.
"""

from flask import Blueprint, request, send_from_directory

from jsonutil import json_response

from . import config, jobs, storage

bp = Blueprint("visuals", __name__, url_prefix="/api/visuals")


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
