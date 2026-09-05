"""Background-thread orchestration for a Visuals generation job --
decoupled from the HTTP layer (see routes.py) and from which provider
actually does the work (see providers/__init__.py's get_provider()). One
job slot at a time, same shape as history/jobs.py and agents/jobs.py.
"""

import threading

from . import providers

_lock = threading.Lock()
_thread: threading.Thread = None
_status = {"phase": "idle", "error": None}   # phase: idle | running | done | error
_result = None   # last completed job's result dict, or None


def _worker(kind: str, params: dict):
    global _result
    try:
        provider = providers.get_provider()
        if kind == "image":
            result = provider.generate_image(
                params["prompt"], image_paths=params.get("image_paths"), **params.get("options", {}),
            )
        elif kind == "video":
            result = provider.generate_video(
                params["prompt"], params["image_path"], **params.get("options", {}),
            )
        else:
            raise ValueError(f"unknown visuals job kind: {kind!r}")
        with _lock:
            _result = {"kind": kind, **result}
            _status["phase"] = "done"
    except Exception as e:
        with _lock:
            _status["phase"] = "error"
            _status["error"] = str(e)


def start(kind: str, params: dict):
    """Returns (ok, error_message)."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return False, "a generation is already in progress"
        _status["phase"] = "running"
        _status["error"] = None
        _thread = threading.Thread(target=_worker, args=(kind, params), daemon=True)
        _thread.start()
    return True, None


def get_status() -> dict:
    with _lock:
        return dict(_status)


def get_result():
    with _lock:
        return _result
