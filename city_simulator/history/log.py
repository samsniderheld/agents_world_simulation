"""A simple append-only log of history-generation progress lines, so the
frontend (the Cities screen's progress panel, the city Inspector's log
panel) can show them live while a generation job runs on its background
thread -- the plain-text analog of recorder.py's structured event log on
the agent side. generate.py calls log() right alongside its existing
print() calls; nothing about the standalone CLI's terminal output changes.

Alongside the lines, a small structured progress record: which stage the
job is in (history -> residents -> summary), how far through it, and how
long the whole job has been running -- what the progress bar reads.
"""

import threading
import time

_lock = threading.Lock()
_lines: list = []

STAGES = ["history", "residents", "summary"]
_progress = {"stage": None, "stages": STAGES, "done": 0, "total": 0, "started": None}


def reset(stages: list = None):
    """Clear the log for a fresh generation run and start its clock;
    `stages` are the ones this run will go through (default: all)."""
    global _lines
    with _lock:
        _lines = []
        _progress.update(stage=None, stages=list(stages or STAGES), done=0, total=0, started=time.monotonic())


def log(line: str):
    with _lock:
        _lines.append(line)


def stage(name: str, total: int = 0):
    """Enter a stage (one of STAGES); `total` items, if it has countable ones."""
    with _lock:
        _progress.update(stage=name, done=0, total=total)


def advance(n: int = 1):
    with _lock:
        _progress["done"] = min(_progress["total"] or 1 << 30, _progress["done"] + n)


def progress() -> dict:
    """{"stage", "stages", "done", "total", "elapsed_seconds"} for the status
    endpoint (elapsed is measured here, so the browser's clock doesn't matter)."""
    with _lock:
        started = _progress["started"]
        return {"stage": _progress["stage"], "stages": _progress["stages"], "done": _progress["done"],
                "total": _progress["total"],
                "elapsed_seconds": round(time.monotonic() - started) if started is not None else None}


def snapshot(since: int = 0):
    """Return (lines recorded after index `since`, current total count),
    for a client to poll incrementally without re-fetching everything."""
    with _lock:
        return list(_lines[since:]), len(_lines)
