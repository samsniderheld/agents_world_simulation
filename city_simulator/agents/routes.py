"""Flask blueprint for the agent-simulation API -- thin view functions
that parse the request and delegate to jobs.py/simulation.py/recorder.py.
"""

from flask import Blueprint, request

from citystate import store as citystate
from jsonutil import json_response

from . import jobs, providers, recorder, simulation, treatment

bp = Blueprint("agents", __name__, url_prefix="/api/agents")


@bp.get("/roster")
def roster():
    return json_response({"roster": simulation.roster_summary()})


@bp.get("/providers")
def provider_list():
    return json_response({"providers": providers.AVAILABLE_PROVIDERS})


@bp.get("/models")
def models():
    provider = request.args.get("provider") or None
    try:
        return json_response({"models": providers.get_provider(provider).list_models()})
    except Exception as e:
        return json_response({"models": [], "error": str(e)})


@bp.get("/state")
def state():
    _, total = recorder.snapshot(0)
    return json_response({
        "status": jobs.get_status(),
        "agents": recorder.get_agents(),
        "meta": recorder.get_meta(),
        "started_at": recorder.get_started_at(),
        "event_count": total,
    })


@bp.get("/events")
def events():
    since = int(request.args.get("since", "0"))
    events, total = recorder.snapshot(since)
    return json_response({"events": events, "next": total})


@bp.post("/run")
def run():
    body = request.get_json(silent=True) or {}
    params = {
        "ticks": int(body.get("ticks", 8)),
        "provider": body.get("provider") or None,
        "tick_sleep": float(body.get("tick_sleep", 0)),
        "chat_model": body.get("chat_model") or None,
        "embed_model": body.get("embed_model") or None,
        "context_tokens": body.get("context_tokens") or None,
        "agent_names": body.get("agent_names") or None,
        "verbose": bool(body.get("verbose", False)),
    }
    ok, error = jobs.start(params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.post("/stop")
def stop():
    jobs.stop()
    return json_response({"ok": True})


@bp.post("/treatment")
def generate_treatment_for_agent():
    """Generates (and persists) a treatment for one agent's most recent
    run -- triggered manually from that agent's modal, see
    treatment.build_transcript()'s docstring for why this needs every
    co-participant's own record, not just this agent's."""
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    record = citystate.get_agent(agent_id) if agent_id else None
    if record is None:
        return json_response({"error": "no such agent"}, status=404)
    runs = record.get("runs") or []
    if not runs:
        return json_response({"error": "this agent has no runs yet"}, status=400)

    city = citystate.get()
    if city is None:
        return json_response({"error": "no active city"}, status=404)

    latest = runs[-1]
    agent_records = {c["name"]: citystate.get_agent(c["id"]) for c in city.get("characters", [])}
    log, agent_names = treatment.build_transcript(agent_records, latest.get("started_at"))

    text = treatment.generate_treatment(log, agent_names)
    entry = citystate.add_treatment(agent_id, text, run_started_at=latest.get("started_at"))
    return json_response({"treatment": entry})
