"""Flask blueprint for history generation (/api/history/*) -- thin view functions that
parse the request and delegate to jobs.py; the actual generation logic
lives in generate.py.
"""

from types import SimpleNamespace

from flask import Blueprint, request

from agents import jobs as agents_jobs
from citystate import store as citystate
from jsonutil import json_response

from . import characters
from . import jobs

bp = Blueprint("history", __name__, url_prefix="/api/history")


@bp.get("/status")
def status():
    return json_response(jobs.get_status())


@bp.get("/data")
def data():
    payload = jobs.get_data()
    if payload is None:
        return json_response({"error": "no history generated yet"}, status=404)
    return json_response(payload)


@bp.get("/log")
def log():
    since = int(request.args.get("since", "0"))
    lines, total = jobs.get_log(since)
    return json_response({"lines": lines, "next": total})


@bp.post("/generate")
def generate():
    """With `city_id` (an existing city): regenerates that specific city in
    place, requiring `confirm_overwrite` first, same as the old single-city
    behavior. Without it: always creates a brand new city -- nothing is
    being destroyed, so no confirmation applies."""
    body = request.get_json(silent=True) or {}
    city_id = body.get("city_id") or None

    if city_id:
        known_ids = {c["id"] for c in citystate.list_cities()}
        if city_id not in known_ids:
            return json_response({"error": f"no such city: {city_id!r}"}, status=404)
        if not body.get("confirm_overwrite"):
            return json_response({
                "ok": False, "needs_confirmation": True,
                "error": "This city already exists and will be permanently replaced.",
            }, status=409)

    params = {
        "seed": body.get("seed"),
        "figures_per_era": body.get("figures_per_era") or None,
        "events_per_figure": body.get("events_per_figure") or None,
        # The web app no longer auto-generates residents as part of history
        # generation -- see POST /characters/preview and POST /characters
        # below for the manual, on-demand replacement. run_history()'s own
        # default (and the CLI's --characters flag) are unaffected.
        "characters_count": 0,
        "use_llm": not bool(body.get("no_llm", False)),
    }
    ok, error = jobs.start(params, city_id=city_id, on_done=agents_jobs.set_history_roster)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.get("/cities")
def list_cities():
    return json_response({"cities": citystate.list_cities()})


@bp.post("/cities/<city_id>/activate")
def activate_city(city_id):
    try:
        citystate.set_active(city_id)
    except RuntimeError as e:
        return json_response({"error": str(e)}, status=404)
    # _active_roster (agents/simulation.py) is a snapshot, not a live view
    # of citystate -- every place that switches which city is active needs
    # to refresh it, same as generate()'s on_done and save_character()
    # below already do.
    agents_jobs.set_history_roster(citystate.get())
    return json_response({"ok": True, "city": citystate.get()})


@bp.delete("/cities/<city_id>")
def delete_city_route(city_id):
    if agents_jobs.get_status().get("phase") == "running":
        return json_response({
            "ok": False, "error": "agents are currently running -- stop them first",
        }, status=409)
    ok, error = jobs.delete_city(city_id)
    if ok and citystate.get_active_id() is None:
        agents_jobs.set_history_roster(None)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.post("/characters/preview")
def preview_character():
    """Generates one new resident, grounded in the active city, without
    persisting anything -- the frontend shows this as an editable draft
    (see main.js's modal shell) before the user decides whether to save
    it via POST /characters below."""
    city = citystate.get()
    if city is None:
        return json_response({"error": "no history generated yet"}, status=404)

    places = [SimpleNamespace(**p) for p in city.get("places", [])]
    figures = [SimpleNamespace(**f) for f in city.get("figures", [])]
    exclude_place_ids = {c["place_id"] for c in city.get("characters", []) if c.get("place_id")}

    body = request.get_json(silent=True) or {}
    place_id = body.get("place_id") or None
    occupation = (body.get("occupation") or "").strip() or None
    sex = (body.get("sex") or "").strip() or None

    try:
        character = characters.generate_one(
            places, figures, exclude_place_ids=exclude_place_ids, force_place_id=place_id,
            occupation=occupation, sex=sex,
        )
    except ValueError as e:
        return json_response({"error": str(e)}, status=400)
    return json_response({"character": character})


@bp.post("/characters")
def save_character():
    """Persists a character -- normally a previewed draft, verbatim or
    edited by the user, from POST /characters/preview above."""
    body = request.get_json(silent=True) or {}
    character = body.get("character") or {}
    if not character.get("id") or not character.get("name"):
        return json_response({"error": "missing character id/name"}, status=400)
    try:
        saved = citystate.add_character(character)
    except RuntimeError as e:
        return json_response({"error": str(e)}, status=409)
    # _active_roster (agents/simulation.py) is a snapshot, not a live view
    # of citystate -- without this, a manually-added character would never
    # show up as addable Agent nodes, only ones present the last time
    # a full history finished generating (or the server started).
    agents_jobs.set_history_roster(citystate.get())
    return json_response({"character": saved})
