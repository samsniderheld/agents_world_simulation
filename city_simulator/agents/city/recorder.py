"""The CITY run's event log. Separate from agents/recorder.py (SCENE's),
so a CITY run never changes what a SCENE run records or serves.

Every event gets a monotonically increasing `seq`, which is the cursor
/api/agents/events hands back; `tier` says whose event it is ("hero",
"background", or None for run-level events like metrics).
"""

import datetime
import threading

_lock = threading.Lock()
_events: list = []
_seq = 0
_started_at: str = None
_heroes: list = []
_meta: dict = {}
_population: dict = {}


def start(heroes: list, meta: dict, population: dict = None):
    global _events, _seq, _started_at, _heroes, _meta, _population
    with _lock:
        _events, _seq = [], 0
        _started_at = datetime.datetime.now().isoformat()
        _heroes = heroes
        _meta = dict(meta or {}, mode="city")
        _population = dict(population or {})


def log(kind: str, tick: int, agent: str = None, tier: str = None, **fields):
    global _seq
    with _lock:
        _seq += 1
        _events.append({"seq": _seq, "kind": kind, "tick": tick, "agent": agent, "tier": tier, **fields})


def snapshot(cursor: int = 0, tier: str = "hero"):
    """(events after `cursor`, next cursor). tier "hero" (default) keeps
    hero and run-level events; "all" keeps everything."""
    with _lock:
        out = [e for e in _events if e["seq"] > cursor and (tier == "all" or e["tier"] != "background")]
        return out, _seq


def state() -> dict:
    with _lock:
        return {
            "agents": [dict(h) for h in _heroes],
            "meta": dict(_meta),
            "started_at": _started_at,
            "event_count": _seq,
            "population": dict(_population),
        }
