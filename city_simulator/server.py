"""The primary interface: a local Flask server serving index.html plus a
small JSON/SSE API for both halves of the app -- history generation
(/api/history/*) and the agent simulation (/api/agents/*). Each runs on its
own background thread with its own status, so the frontend can drive both
independently: generate a history in the first tab, then (once it's done)
run agents seeded from it in the second.

Usage:
    python3 server.py
"""

import json
import logging
import os
import threading
import time
import webbrowser

from flask import Flask, Response, request, send_from_directory
from werkzeug.serving import make_server

import agent_llm as llm
import history_generate
import history_log
import recorder
import simulation

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
STREAM_POLL_SECONDS = 0.25

# The frontend is the interface now; keep the terminal quiet (matches the
# old bare http.server Handler's log_message no-op).
logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)


def _json_response(payload, status=200):
    # Plain json.dumps (with default=str, same as the rest of this app's
    # JSON output) instead of Flask's jsonify -- keeps datetime/dataclass
    # leftovers from breaking a response the same defensive way the rest
    # of the app already handles them.
    return Response(json.dumps(payload, default=str), status=status, mimetype="application/json")


# --- history generation job (tab 1) -------------------------------------

_history_lock = threading.Lock()
_history_thread: threading.Thread = None
_history_status = {"phase": "idle", "error": None}   # phase: idle | running | done | error
_history_data = None   # last completed run's full payload, or None


def _history_worker(params: dict):
    global _history_data
    try:
        payload = history_generate.run_history(**params)
        with _history_lock:
            _history_data = payload
            _history_status["phase"] = "done"
        simulation.set_history_roster(payload)
    except Exception as e:
        with _history_lock:
            _history_status["phase"] = "error"
            _history_status["error"] = str(e)


def _start_history(params: dict):
    """Returns (ok, error_message)."""
    global _history_thread
    with _history_lock:
        if _history_thread and _history_thread.is_alive():
            return False, "a history generation is already in progress"
        _history_status["phase"] = "running"
        _history_status["error"] = None
        _history_thread = threading.Thread(target=_history_worker, args=(params,), daemon=True)
        _history_thread.start()
    return True, None


# --- agent simulation run (tab 2) ----------------------------------------

_agents_lock = threading.Lock()
_agents_thread: threading.Thread = None
_agents_stop_flag = threading.Event()
_agents_status = {"phase": "idle", "error": None}   # phase: idle | running | done | error


def _agents_worker(params: dict):
    try:
        simulation.run(stop_flag=_agents_stop_flag, **params)
        with _agents_lock:
            _agents_status["phase"] = "done"
    except Exception as e:
        with _agents_lock:
            _agents_status["phase"] = "error"
            _agents_status["error"] = str(e)


def _start_agents(params: dict):
    """Returns (ok, error_message)."""
    global _agents_thread
    with _agents_lock:
        if _agents_thread and _agents_thread.is_alive():
            return False, "a run is already in progress"
        _agents_stop_flag.clear()
        _agents_status["phase"] = "running"
        _agents_status["error"] = None
        _agents_thread = threading.Thread(target=_agents_worker, args=(params,), daemon=True)
        _agents_thread.start()
    return True, None


# --- static ---------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(DIRECTORY, "index.html")


# --- history routes ---------------------------------------------------------

@app.get("/api/history/status")
def history_status():
    with _history_lock:
        return _json_response(dict(_history_status))


@app.get("/api/history/data")
def history_data():
    with _history_lock:
        data = _history_data
    if data is None:
        return _json_response({"error": "no history generated yet"}, status=404)
    return _json_response(data)


@app.get("/api/history/log")
def history_log_route():
    since = int(request.args.get("since", "0"))
    lines, total = history_log.snapshot(since)
    return _json_response({"lines": lines, "next": total})


@app.post("/api/history/generate")
def history_generate_route():
    body = request.get_json(silent=True) or {}
    params = {
        "seed": body.get("seed"),
        "figures_per_era": body.get("figures_per_era") or None,
        "events_per_figure": body.get("events_per_figure") or None,
        "characters_count": int(body.get("characters") or 10),
        "use_llm": not bool(body.get("no_llm", False)),
    }
    ok, error = _start_history(params)
    return _json_response({"ok": ok, "error": error}, status=200 if ok else 409)


# --- agent routes -----------------------------------------------------------

@app.get("/api/agents/roster")
def agents_roster():
    return _json_response({"roster": simulation.roster_summary()})


@app.get("/api/agents/models")
def agents_models():
    try:
        return _json_response({"models": llm.list_models()})
    except Exception as e:
        return _json_response({"models": [], "error": str(e)})


@app.get("/api/agents/state")
def agents_state():
    with _agents_lock:
        status = dict(_agents_status)
    _, total = recorder.snapshot(0)
    return _json_response({
        "status": status,
        "agents": recorder.get_agents(),
        "meta": recorder.get_meta(),
        "started_at": recorder.get_started_at(),
        "event_count": total,
    })


@app.get("/api/agents/events")
def agents_events():
    since = int(request.args.get("since", "0"))
    events, total = recorder.snapshot(since)
    return _json_response({"events": events, "next": total})


@app.get("/api/agents/stream")
def agents_stream():
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


@app.post("/api/agents/run")
def agents_run():
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
    ok, error = _start_agents(params)
    return _json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@app.post("/api/agents/stop")
def agents_stop():
    _agents_stop_flag.set()
    return _json_response({"ok": True})


def main():
    # make_server (not app.run()) so an ephemeral port (0) resolves to a
    # real port we can print/open a browser to, and threaded=True so the
    # long-lived SSE stream doesn't block other requests.
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    url = f"http://127.0.0.1:{srv.server_port}/"
    print(f"Serving City Simulator at {url} (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
