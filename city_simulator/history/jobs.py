"""Background-thread orchestration for a history-generation run --
decoupled from the HTTP layer (see routes.py), the same split
agents/jobs.py uses for the agent-simulation run.

The completed payload itself isn't held here -- get_data() reads straight
through to citystate.store, the one place the active city lives (in
memory and on disk), so a media attachment or agent run appended there
later is what /api/history/data also sees, with no second copy to fall
out of sync.
"""

import threading

from citystate import store as citystate

from . import generate as history_generate
from . import log as history_log

_lock = threading.Lock()
_thread: threading.Thread = None
# A previously-persisted city (citystate.store lazily loads it from disk on
# this very call) means there's already something to show -- start the
# status as "done" rather than "idle" so the frontend's first status poll
# fetches /api/history/data on its own, the same way it would right after
# a fresh generation, instead of leaving the empty state up until someone
# clicks Generate again.
_status = {
    "phase": "done" if citystate.get() is not None else "idle", "error": None,
}   # phase: idle | running | done | error


def _worker(params: dict, on_done):
    try:
        payload = history_generate.run_history(**params)
        citystate.replace(payload)
        with _lock:
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
    return citystate.get()


def get_log(since: int = 0):
    return history_log.snapshot(since)
