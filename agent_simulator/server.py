"""The primary interface: a local web server serving index.html plus a
small JSON/SSE API. Runs simulations on a background thread so the
frontend can configure, start, stop, and watch a run live -- multiple
agents thinking concurrently, streamed as they go -- instead of driving
everything from the terminal.

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

import llm
import recorder
import simulation

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
STREAM_POLL_SECONDS = 0.25

_state_lock = threading.Lock()
_run_thread: threading.Thread = None
_stop_flag = threading.Event()
_status = {"phase": "idle", "error": None}   # phase: idle | running | done | error


def _run_worker(params: dict):
    try:
        simulation.run(stop_flag=_stop_flag, **params)
        with _state_lock:
            _status["phase"] = "done"
    except Exception as e:
        with _state_lock:
            _status["phase"] = "error"
            _status["error"] = str(e)


def _start_run(params: dict):
    """Returns (ok, error_message)."""
    global _run_thread
    with _state_lock:
        if _run_thread and _run_thread.is_alive():
            return False, "a run is already in progress"
        _stop_flag.clear()
        _status["phase"] = "running"
        _status["error"] = None
        _run_thread = threading.Thread(target=_run_worker, args=(params,), daemon=True)
        _run_thread.start()
    return True, None


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        pass  # the frontend is the interface now; keep the terminal quiet

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
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

        if path == "/api/roster":
            return self._send_json({"roster": simulation.roster_summary()})

        if path == "/api/models":
            try:
                return self._send_json({"models": llm.list_models()})
            except Exception as e:
                return self._send_json({"models": [], "error": str(e)})

        if path == "/api/state":
            with _state_lock:
                status = dict(_status)
            _, total = recorder.snapshot(0)
            return self._send_json({
                "status": status,
                "agents": recorder.get_agents(),
                "meta": recorder.get_meta(),
                "started_at": recorder.get_started_at(),
                "event_count": total,
            })

        if path == "/api/events":
            since = int(self._query().get("since", ["0"])[0])
            events, total = recorder.snapshot(since)
            return self._send_json({"events": events, "next": total})

        if path == "/api/stream":
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
                    chunk = f"data: {json.dumps(ev)}\n\n".encode()
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

        if path == "/api/run":
            params = {
                "ticks": int(body.get("ticks", 8)),
                "tick_sleep": float(body.get("tick_sleep", 0)),
                "chat_model": body.get("chat_model") or None,
                "embed_model": body.get("embed_model") or None,
                "context_tokens": body.get("context_tokens") or None,
                "agent_names": body.get("agent_names") or None,
                "verbose": bool(body.get("verbose", False)),
            }
            ok, error = _start_run(params)
            return self._send_json({"ok": ok, "error": error}, status=200 if ok else 409)

        if path == "/api/stop":
            _stop_flag.set()
            return self._send_json({"ok": True})

        return self._send_json({"ok": False, "error": "not found"}, status=404)


def main():
    # ThreadingHTTPServer (not plain ThreadingTCPServer) sets
    # daemon_threads=True, so long-lived SSE connection threads don't block
    # process exit on Ctrl+C.
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"Serving Agent Console at {url} (Ctrl+C to stop)")
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
