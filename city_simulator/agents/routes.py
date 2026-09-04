"""Flask blueprint for the Agents tab's API -- thin view functions that
parse the request and delegate to jobs.py/simulation.py/recorder.py.
"""

import json
import time

from flask import Blueprint, Response, request

from jsonutil import json_response

from . import jobs, llm, recorder, simulation

bp = Blueprint("agents", __name__, url_prefix="/api/agents")

STREAM_POLL_SECONDS = 0.25


@bp.get("/roster")
def roster():
    return json_response({"roster": simulation.roster_summary()})


@bp.get("/models")
def models():
    try:
        return json_response({"models": llm.list_models()})
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


@bp.get("/stream")
def stream():
    """Server-Sent Events: push new recorder events as they land."""
    since = int(request.args.get("since", "0"))

    def generate():
        # An immediate SSE comment line (ignored by EventSource, unlike a
        # "data:" line) so Werkzeug flushes the response headers right
        # away instead of buffering until the first real event -- without
        # this, a client connecting before anything has happened yet sees
        # no response at all until something finally occurs. The same
        # comment doubles as a keepalive on every empty poll after that.
        yield ": connected\n\n"
        cursor = since
        while True:
            events, total = recorder.snapshot(cursor)
            if events:
                for ev in events:
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
            else:
                yield ": keepalive\n\n"
            cursor = total
            time.sleep(STREAM_POLL_SECONDS)

    return Response(generate(), mimetype="text/event-stream",
                     headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@bp.post("/run")
def run():
    body = request.get_json(silent=True) or {}
    params = {
        "ticks": int(body.get("ticks", 8)),
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
