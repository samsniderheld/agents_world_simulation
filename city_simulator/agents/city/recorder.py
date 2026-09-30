"""The CITY run's event log. Separate from agents/recorder.py (SCENE's),
so a CITY run never changes what a SCENE run records or serves.

Every event gets a monotonically increasing `seq`, which is the cursor
/api/agents/events hands back; `tier` says whose event it is ("hero",
"background", or None for run-level events like metrics).

Besides the live log this keeps, for the end of the run:
- every hero's own events in full (what gets appended to their citystate
  record, exactly as a SCENE run's are -- including memory embeddings),
- where every agent was at every tick (for zooming into a place and time).
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
_hero_events: dict = {}      # hero name -> [event], full (with embeddings)
_positions: list = []        # per tick: {agent name: location label}
_last_metrics: dict = None


def start(heroes: list, meta: dict, population: dict = None):
    global _events, _seq, _started_at, _heroes, _meta, _population, _hero_events, _positions, _last_metrics
    with _lock:
        _events, _seq = [], 0
        _started_at = datetime.datetime.now().isoformat()
        _heroes = [dict(h) for h in heroes]
        _meta = dict(meta or {}, mode="city")
        _population = dict(population or {})
        _hero_events = {h["name"]: [] for h in heroes}
        _positions = []
        _last_metrics = None


def log(kind: str, tick: int, agent: str = None, tier: str = None, keep_for: tuple = (), **fields):
    """Append one event. `keep_for` names heroes whose persisted record
    gets this event too (besides `agent` itself when it's a hero) -- e.g. a
    background resident's line spoken to a hero."""
    global _seq, _last_metrics
    with _lock:
        _seq += 1
        event = {"seq": _seq, "kind": kind, "tick": tick, "agent": agent, "tier": tier, **fields}
        full = event
        if "embedding" in fields:           # the live log doesn't need 768 floats per memory
            event = {k: v for k, v in event.items() if k != "embedding"}
        _events.append(event)
        if kind == "metrics":
            _last_metrics = event
        for name in ({agent} if agent in _hero_events else set()) | set(keep_for):
            if name in _hero_events:
                _hero_events[name].append(full)


def add_hero(hero: dict):
    """A background resident promoted to hero mid-run."""
    with _lock:
        _heroes.append(dict(hero))
        _hero_events.setdefault(hero["name"], [])
        _population["heroes"] = len(_heroes)
        _population["background"] = max(0, _population.get("background", 0) - 1)


def update_hero_location(name: str, location: str):
    with _lock:
        for h in _heroes:
            if h["name"] == name:
                h["location"] = location
                break


def set_positions(tick: int, positions: dict):
    with _lock:
        while len(_positions) <= tick:
            _positions.append({})
        _positions[tick] = dict(positions)


def set_meta(**fields):
    with _lock:
        _meta.update(fields)


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
            "metrics": dict(_last_metrics) if _last_metrics else None,
        }


def hero_events() -> dict:
    with _lock:
        return {k: list(v) for k, v in _hero_events.items()}


def positions() -> list:
    with _lock:
        return [dict(p) for p in _positions]


def run_info() -> dict:
    with _lock:
        return {"started_at": _started_at, "meta": dict(_meta), "heroes": [dict(h) for h in _heroes]}
