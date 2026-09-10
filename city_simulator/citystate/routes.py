"""Flask blueprint for the persisted city record's own small API --
attaching/removing media on a character or place. The city payload itself
is still read through /api/history/data (history/routes.py); this
blueprint only covers what history/routes.py doesn't own: media records.
"""

from flask import Blueprint, request

from jsonutil import json_response

from . import store

bp = Blueprint("city", __name__, url_prefix="/api/city")


@bp.get("/state")
def state():
    payload = store.get()
    if payload is None:
        return json_response({"error": "no active city"}, status=404)
    return json_response(payload)


@bp.post("/media")
def add_media():
    body = request.get_json(silent=True) or {}
    entity_id = body.get("entity_id")
    kind = body.get("kind")
    url = body.get("url")
    if not entity_id or kind not in ("image", "video") or not url:
        return json_response({"ok": False, "error": "entity_id, kind (image|video), and url are required"}, status=400)
    try:
        media = store.add_media(
            entity_id, kind, url,
            local_path=body.get("local_path", ""), prompt=body.get("prompt", ""),
            tag=body.get("tag", ""),
        )
    except RuntimeError as e:
        return json_response({"ok": False, "error": str(e)}, status=409)
    return json_response({"ok": True, "media": media})


@bp.delete("/media/<entity_id>/<media_id>")
def remove_media(entity_id, media_id):
    ok = store.remove_media(entity_id, media_id)
    return json_response({"ok": ok}, status=200 if ok else 404)
