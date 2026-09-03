"""The primary interface: a local web server serving index.html plus a
small JSON/SSE API for both halves of the app -- history generation
(/api/history/*) and the agent simulation (/api/agents/*). Each runs on its
own background thread with its own status, so the frontend can drive both
independently: generate a history in the first tab, then (once it's done)
run agents seeded from it in the second.

Usage:
    python3 server.py
"""

import http.server
import json
import os
import threading
import time
import webbrowser
from urllib.parse import urlparse, parse_qs

import agent_llm as llm
import history_generate
import history_log
import recorder
import simulation

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
STREAM_POLL_SECONDS = 0.25

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


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        pass  # the frontend is the interface now; keep the terminal quiet

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query(self) -> dict:
        return parse_qs(urlparse(self.path).query)

    def _path(self) -> str:
        return urlparse(self.path).path

    # --- GET routes ---------------------------------------------------

    def do_GET(self):
        path = self._path()

        if path == "/api/history/status":
            with _history_lock:
                return self._send_json(dict(_history_status))

        if path == "/api/history/data":
            with _history_lock:
                data = _history_data
            if data is None:
                return self._send_json({"error": "no history generated yet"}, status=404)
            return self._send_json(data)

        if path == "/api/history/log":
            since = int(self._query().get("since", ["0"])[0])
            lines, total = history_log.snapshot(since)
            return self._send_json({"lines": lines, "next": total})

        if path == "/api/agents/roster":
            return self._send_json({"roster": simulation.roster_summary()})

        if path == "/api/agents/models":
            try:
                return self._send_json({"models": llm.list_models()})
            except Exception as e:
                return self._send_json({"models": [], "error": str(e)})

        if path == "/api/agents/state":
            with _agents_lock:
                status = dict(_agents_status)
            _, total = recorder.snapshot(0)
            return self._send_json({
                "status": status,
                "agents": recorder.get_agents(),
                "meta": recorder.get_meta(),
                "started_at": recorder.get_started_at(),
                "event_count": total,
            })

        if path == "/api/agents/events":
            since = int(self._query().get("since", ["0"])[0])
            events, total = recorder.snapshot(since)
            return self._send_json({"events": events, "next": total})

        if path == "/api/agents/stream":
            return self._stream()

        return super().do_GET()

    def _stream(self):
        """Server-Sent Events: push new recorder events as they land."""
        since = int(self._query().get("since", ["0"])[0])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                events, total = recorder.snapshot(since)
                for ev in events:
                    chunk = f"data: {json.dumps(ev, default=str)}\n\n".encode()
                    self.wfile.write(chunk)
                if events:
                    self.wfile.flush()
                since = total
                time.sleep(STREAM_POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError):
            return

    # --- POST routes ----------------------------------------------------

    def do_POST(self):
        path = self._path()
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._send_json({"ok": False, "error": "invalid JSON body"}, status=400)

        if path == "/api/history/generate":
            params = {
                "seed": body.get("seed"),
                "figures_per_era": body.get("figures_per_era") or None,
                "events_per_figure": body.get("events_per_figure") or None,
                "characters_count": int(body.get("characters") or 10),
                "use_llm": not bool(body.get("no_llm", False)),
            }
            ok, error = _start_history(params)
            return self._send_json({"ok": ok, "error": error}, status=200 if ok else 409)

        if path == "/api/agents/run":
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
            return self._send_json({"ok": ok, "error": error}, status=200 if ok else 409)

        if path == "/api/agents/stop":
            _agents_stop_flag.set()
            return self._send_json({"ok": True})

        return self._send_json({"ok": False, "error": "not found"}, status=404)


def main():
    # ThreadingHTTPServer (not plain ThreadingTCPServer) sets
    # daemon_threads=True, so long-lived SSE connection threads don't block
    # process exit on Ctrl+C.
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"Serving City Simulator at {url} (Ctrl+C to stop)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
