"""Structured event log for a single simulation run.

Every plan, decompose, observe/react, memory, reflection, action, and
dialogue event is appended here as it happens -- regardless of --verbose.
server.py serves this live (polling it from an SSE endpoint) while agents
run concurrently on background threads, so every access is guarded by a
lock; a run's final state is also dumped to run_log.json for offline
inspection.

Event shape: {"kind": str, "tick": int, "agent": str | None, ...fields}
  plan          items: [str]
  decompose     broad_step: str, items: [str]
  observe       text: str
  react         text: str
  continue      (no extra fields)
  memory        memory_kind: str, importance: float, text: str
  focal         text: str
  insight       text: str, evidence: [int]
  action        text: str, location: str, time: str
  dialogue      text: str, listener: str
  reflect_pause (no extra fields)
  treatment     text: str
"""

import datetime
import json
import threading

_lock = threading.Lock()
_events: list = []
_started_at: str = None
_agents: list = []
_meta: dict = {}


def start(agents: list, meta: dict = None):
    """Reset the log for a fresh run. `agents` should be a list of dicts
    (name/color/etc, see simulation.py) so a viewer can build a legend
    before any events arrive."""
    global _events, _started_at, _agents, _meta
    with _lock:
        _events = []
        _started_at = datetime.datetime.now().isoformat()
        _agents = agents
        _meta = meta or {}


def log(kind: str, tick: int, agent: str = None, **fields):
    """Append one structured event. Safe to call from multiple agent
    threads at once."""
    with _lock:
        _events.append({"kind": kind, "tick": tick, "agent": agent, **fields})


def snapshot(since: int = 0):
    """Return (events recorded after index `since`, current total count),
    for a client to poll incrementally without re-fetching everything."""
    with _lock:
        return list(_events[since:]), len(_events)


def get_agents() -> list:
    with _lock:
        return list(_agents)


def get_meta() -> dict:
    with _lock:
        return dict(_meta)


def get_started_at() -> str:
    return _started_at


def save(path: str = "run_log.json") -> str:
    """Write the whole run (agents, meta, events so far) to `path`."""
    with _lock:
        payload = {
            "started_at": _started_at,
            "agents": _agents,
            "meta": _meta,
            "events": list(_events),
        }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path
