"""A simple append-only log of history-generation progress lines, so
server.py's History tab can show them live (like a terminal) while a
generation job runs on its background thread -- the plain-text analog of
recorder.py's structured event log on the agent side. history_generate.py
calls log() right alongside its existing print() calls; nothing about the
standalone CLI's terminal output changes.
"""

import threading

_lock = threading.Lock()
_lines: list = []


def reset():
    """Clear the log for a fresh generation run."""
    global _lines
    with _lock:
        _lines = []


def log(line: str):
    with _lock:
        _lines.append(line)


def snapshot(since: int = 0):
    """Return (lines recorded after index `since`, current total count),
    for a client to poll incrementally without re-fetching everything."""
    with _lock:
        return list(_lines[since:]), len(_lines)
