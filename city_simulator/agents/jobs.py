"""Background-thread orchestration for an agent-simulation run --
decoupled from the HTTP layer (see routes.py). `set_history_roster` is
re-exported from simulation.py so history/routes.py can hand it to
history.jobs.start() as an on-done callback without importing simulation.py
directly.
"""

import threading

from . import simulation
from .simulation import set_history_roster  # noqa: F401 -- re-exported

_lock = threading.Lock()
_thread: threading.Thread = None
_stop_flag = threading.Event()
_status = {"phase": "idle", "error": None}   # phase: idle | running | done | error


def _worker(params: dict):
    try:
        simulation.run(stop_flag=_stop_flag, **params)
        with _lock:
            _status["phase"] = "done"
    except Exception as e:
        with _lock:
            _status["phase"] = "error"
            _status["error"] = str(e)


def start(params: dict):
    """Returns (ok, error_message)."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return False, "a run is already in progress"
        _stop_flag.clear()
        _status["phase"] = "running"
        _status["error"] = None
        _thread = threading.Thread(target=_worker, args=(params,), daemon=True)
        _thread.start()
    return True, None


def stop():
    _stop_flag.set()


def get_status() -> dict:
    with _lock:
        return dict(_status)
