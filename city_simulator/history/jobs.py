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


def _worker(params: dict, city_id: str, on_done):
    try:
        payload = history_generate.run_history(**params)
        citystate.replace(payload, city_id=city_id)
        with _lock:
            _status["phase"] = "done"
        if on_done:
            on_done(payload)
    except Exception as e:
        with _lock:
            _status["phase"] = "error"
            _status["error"] = str(e)


def start(params: dict, city_id: str = None, on_done=None):
    """Returns (ok, error_message). `city_id` (an existing city, for a
    regenerate-in-place) is kept separate from `params` -- it's not one of
    run_history()'s own arguments, only citystate.replace()'s -- so it's
    threaded straight through to _worker rather than mixed into the
    **params spread. `on_done(payload)` is called (outside the lock) once
    generation finishes successfully -- routes.py uses this to hand the
    result to agents.jobs.set_history_roster()."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return False, "a history generation is already in progress"
        _status["phase"] = "running"
        _status["error"] = None
        _thread = threading.Thread(target=_worker, args=(params, city_id, on_done), daemon=True)
        _thread.start()
    return True, None


def delete_city(city_id: str):
    """Removes one city from the collection (it need not be the active
    one). Refuses while a generation is running: the job in progress could
    be regenerating exactly this city_id in place."""
    with _lock:
        if _thread and _thread.is_alive():
            return False, "a history generation is already in progress"
        was_active = citystate.get_active_id() == city_id
        citystate.delete_city(city_id)
        if was_active:
            history_log.reset()
            _status["phase"] = "idle"
            _status["error"] = None
    return True, None


def get_status() -> dict:
    with _lock:
        return dict(_status)


def get_data():
    return citystate.get()


def get_log(since: int = 0):
    return history_log.snapshot(since)
