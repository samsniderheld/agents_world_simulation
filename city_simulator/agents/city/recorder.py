"""The CITY run's event log. Separate from agents/recorder.py (SCENE's),
so a CITY run never changes what a SCENE run records or serves.

Level of detail: heroes get every event (plan, decompose, action, observe,
react, dialogue, memory, focal, insight, move, ...); background residents
only get move / encounter / promotion events, plus one run-level
"tick_summary" per tick (occupancy by place, counts). Run-level events
(status, metrics, tick_summary) have tier None.

The live log is a ring buffer (config.EVENT_BUFFER_SIZE): at 1000 agents a
long run would otherwise grow without bound. Every event gets a
monotonically increasing `seq`, which is the cursor /api/agents/events
pages with; a client whose cursor fell out of the buffer is told how many
events it missed.

Besides the live log this keeps, for the end of the run:
- every hero's own events in full (what gets appended to their citystate
  record, exactly as a SCENE run's are -- including memory embeddings),
- where every agent was at every tick (for zooming into a place and time).
"""

import collections
import datetime
import threading

from . import config as ccfg

_lock = threading.Lock()
_events = collections.deque(maxlen=ccfg.EVENT_BUFFER_SIZE)
_seq = 0
_started_at: str = None
_heroes: list = []
_meta: dict = {}
_population: dict = {}
_hero_events: dict = {}      # hero name -> [event], full (with embeddings)
_positions: list = []        # per tick: {agent name: location label}
_last_metrics: dict = None
_run_first_seq = 1           # seq of this run's first event


def start(heroes: list, meta: dict, population: dict = None):
    global _events, _started_at, _heroes, _meta, _population, _hero_events, _positions, _last_metrics, _run_first_seq
    with _lock:
        _run_first_seq = _seq + 1
        # `_seq` keeps counting across runs, so a client's cursor from an
        # earlier run can never skip the start of this one.
        _events = collections.deque(maxlen=ccfg.EVENT_BUFFER_SIZE)
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
    page = query(cursor, tier=tier, limit=None)
    return page["events"], page["next"]


def query(cursor: int = 0, tier: str = "hero", kinds: set = None, agent: str = None, place: str = None,
          limit: int = 500) -> dict:
    """One page of the live log after `cursor`:
      tier   "hero" (default: heroes + run-level), "background", or "all"
      kinds  only these event kinds
      agent  only events by or addressed to this agent
      place  only events at this place
    Returns {"events", "next" (the cursor for the next page), "dropped"
    (events after `cursor` that already left the ring buffer)}. With a
    filter, "next" still advances past everything scanned, so paging never
    re-reads skipped events."""
    with _lock:
        first = _events[0]["seq"] if _events else _seq + 1
        run_start = _run_first_seq
        dropped = max(0, first - max(cursor, run_start - 1) - 1)
        out = []
        last = cursor
        full = False
        for e in _events:
            if e["seq"] <= cursor:
                continue
            if limit is not None and len(out) >= limit:
                full = True
                break
            last = e["seq"]
            if tier == "hero" and e["tier"] == "background":
                continue
            if tier == "background" and e["tier"] != "background":
                continue
            if kinds and e["kind"] not in kinds:
                continue
            if agent and e.get("agent") != agent and e.get("listener") != agent and e.get("other") != agent:
                continue
            if place and place not in (e.get("location"), e.get("place"), e.get("to_location"), e.get("from_location")):
                continue
            out.append(e)
        return {"events": out, "next": last if full else max(cursor, _seq), "dropped": dropped,
                "started_at": _started_at}


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
