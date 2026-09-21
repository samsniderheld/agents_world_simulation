"""Flask blueprint for the global style library -- GET/POST/DELETE
/api/styles. Its own top-level prefix (not nested under /api/visuals/*)
since a style is a first-class, reusable object a Style node points at,
not a visuals-generation *action* the way generate-image/etc. are.
"""

from pathlib import Path

from flask import Blueprint, request, send_file

from jsonutil import json_response

from . import config, styles

bp = Blueprint("styles", __name__, url_prefix="/api/styles")


@bp.get("/")
def list_all():
    return json_response({"styles": styles.list_styles()})


@bp.get("/reference-image")
def reference_image():
    """Serves a style's reference image by the real absolute filesystem
    path stored in reference_images -- that path is the exact string
    forwarded to the provider as image_paths (see visuals/routes.py's
    _style_reference_images()), so it can't be relativized without
    breaking generation; this exists purely so a Style node can *display*
    it. Scoped to UPLOADS_DIR (the only place StyleNode.tsx's addReference
    ever writes to) rather than serving any path a caller names.
    """
    raw = request.args.get("path", "")
    try:
        resolved = Path(raw).resolve(strict=True)
        resolved.relative_to(config.UPLOADS_DIR.resolve())
    except (ValueError, OSError, RuntimeError):
        return json_response({"error": "not found"}, status=404)
    return send_file(resolved)


@bp.post("/")
def create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return json_response({"error": "name is required"}, status=400)
    # style_prompt is deliberately allowed blank -- a Style node starts
    # empty and gets filled in on the canvas afterward, same as every
    # other generation node (Image/Frame/Video all start with an empty
    # prompt too); requiring it up front only made sense for a
    # fully-formed API call, not the "+ Style" creation flow.
    style = styles.create_style(
        name=name,
        style_prompt=(body.get("style_prompt") or "").strip(),
        reference_images=body.get("reference_images") or [],
    )
    return json_response({"style": style})


@bp.put("/<style_id>")
def update(style_id):
    body = request.get_json(silent=True) or {}
    try:
        style = styles.update_style(
            style_id,
            name=body.get("name"),
            style_prompt=body.get("style_prompt"),
            reference_images=body.get("reference_images"),
        )
    except KeyError:
        return json_response({"error": f"no such style: {style_id!r}"}, status=404)
    return json_response({"style": style})


@bp.delete("/<style_id>")
def delete(style_id):
    ok = styles.delete_style(style_id)
    return json_response({"ok": ok}, status=200 if ok else 404)
