"""Flask blueprint for the History tab's API -- thin view functions that
parse the request and delegate to jobs.py; the actual generation logic
lives in generate.py.
"""

from flask import Blueprint, request

from agents import jobs as agents_jobs
from jsonutil import json_response

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
    body = request.get_json(silent=True) or {}
    params = {
        "seed": body.get("seed"),
        "figures_per_era": body.get("figures_per_era") or None,
        "events_per_figure": body.get("events_per_figure") or None,
        "characters_count": int(body.get("characters") or 10),
        "use_llm": not bool(body.get("no_llm", False)),
    }
    ok, error = jobs.start(params, on_done=agents_jobs.set_history_roster)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)
