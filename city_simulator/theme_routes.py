"""Blueprint: /api/themes -- list, download, upload and delete city themes
(theme.py). Built-in themes live in themes/; uploaded ones in
citystate/data/themes/. A city's own copy is downloadable too."""

from flask import Blueprint, Response, request

import theme
from citystate import store as citystate
from jsonutil import json_response

bp = Blueprint("themes", __name__, url_prefix="/api/themes")


def _yaml_download(text: str, filename: str) -> Response:
    return Response(text, mimetype="application/x-yaml",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@bp.get("")
def list_themes():
    active = citystate.get_active_id()
    return json_response({
        "themes": theme.list_themes(),
        "default": theme.DEFAULT_ID,
        "active_city_theme": theme.for_city(active).summary() if active else None,
    })


@bp.get("/reference")
def reference():
    """For theme authors: every prompt and the {slots} the app fills in it."""
    return json_response({"prompts": {k: sorted(v) for k, v in sorted(theme.prompt_slots().items())}})


@bp.get("/<theme_id>/file")
def download(theme_id):
    try:
        t = theme.get(theme_id)
    except KeyError as e:
        return json_response({"error": str(e)}, status=404)
    return _yaml_download(t.text, f"{t.id}.yaml")


@bp.get("/city/<city_id>/file")
def download_city_theme(city_id):
    """The theme a city was generated with (its own copy)."""
    if city_id not in {c["id"] for c in citystate.list_cities()}:
        return json_response({"error": f"no such city: {city_id!r}"}, status=404)
    t = theme.for_city(city_id)
    return _yaml_download(t.text, f"{t.id}.yaml")


@bp.post("")
def upload():
    """The theme file as the raw request body (or JSON {"text": ...}).
    400 with every problem found if it doesn't validate."""
    if request.is_json:
        text = (request.get_json(silent=True) or {}).get("text") or ""
    else:
        text = request.get_data(as_text=True)
    if not text.strip():
        return json_response({"ok": False, "problems": ["the file is empty"]}, status=400)
    if len(text) > 2_000_000:
        return json_response({"ok": False, "problems": ["the file is larger than 2 MB"]}, status=400)
    try:
        t = theme.save_upload(text)
    except theme.ThemeError as e:
        return json_response({"ok": False, "problems": e.problems}, status=400)
    return json_response({"ok": True, "theme": t.summary()})


@bp.delete("/<theme_id>")
def delete(theme_id):
    if theme.delete_upload(theme_id):
        return json_response({"ok": True})
    return json_response({"ok": False, "error": "only uploaded themes can be deleted"}, status=400)
