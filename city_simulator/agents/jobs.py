"""Background-thread orchestration for an agent-simulation run --
decoupled from the HTTP layer (see routes.py). One slot, one stop flag and
one status for both modes: a SCENE run (simulation.run) or a CITY run
(city.run.run) -- only one run of either mode at a time. `set_history_roster` is
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
# Mode of the current (or most recent) run; None before the first run.
_mode = None


def _worker(mode: str, params: dict):
    try:
        if mode == "city":
            from .city import run as city_run
            city_run.run(stop_flag=_stop_flag, **params)
        else:
            simulation.run(stop_flag=_stop_flag, **params)
        with _lock:
            _status["phase"] = "done"
    except Exception as e:
        with _lock:
            _status["phase"] = "error"
            _status["error"] = str(e)


def start(params: dict, mode: str = "scene"):
    """Returns (ok, error_message). `mode` is "scene" (the default --
    simulation.run) or "city" (city.run.run)."""
    global _thread, _mode
    with _lock:
        if _thread and _thread.is_alive():
            return False, "a run is already in progress"
        _stop_flag.clear()
        _status["phase"] = "running"
        _status["error"] = None
        _mode = mode
        _thread = threading.Thread(target=_worker, args=(mode, params), daemon=True)
        _thread.start()
    return True, None


def stop():
    _stop_flag.set()


def get_status() -> dict:
    with _lock:
        return dict(_status)


def current_mode() -> str:
    """"scene" or "city" -- the mode of the current or most recent run
    ("scene" before any run, so the endpoints behave as they always have)."""
    with _lock:
        return _mode or "scene"
