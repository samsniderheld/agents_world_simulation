"""Background-thread orchestration for a history-generation run --
decoupled from the HTTP layer (see routes.py), the same split
agents/jobs.py uses for the agent-simulation run.
"""

import threading

from . import generate as history_generate
from . import log as history_log

_lock = threading.Lock()
_thread: threading.Thread = None
_status = {"phase": "idle", "error": None}   # phase: idle | running | done | error
_data = None   # last completed run's full payload, or None


def _worker(params: dict, on_done):
    global _data
    try:
        payload = history_generate.run_history(**params)
        with _lock:
            _data = payload
            _status["phase"] = "done"
        if on_done:
            on_done(payload)
    except Exception as e:
        with _lock:
            _status["phase"] = "error"
            _status["error"] = str(e)


def start(params: dict, on_done=None):
    """Returns (ok, error_message). `on_done(payload)` is called (outside
    the lock) once generation finishes successfully -- routes.py uses this
    to hand the result to agents.jobs.set_history_roster()."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return False, "a history generation is already in progress"
        _status["phase"] = "running"
        _status["error"] = None
        _thread = threading.Thread(target=_worker, args=(params, on_done), daemon=True)
        _thread.start()
    return True, None


def get_status() -> dict:
    with _lock:
        return dict(_status)


def get_data():
    with _lock:
        return _data


def get_log(since: int = 0):
    return history_log.snapshot(since)
