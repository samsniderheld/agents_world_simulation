"""Structured event log for a single simulation run.

Every plan, decompose, observe/react, memory, reflection, action, and
dialogue event is appended here as it happens -- regardless of --verbose --
then main.py dumps the whole run to a single JSON file (overwritten each
run) for viewer.html to render as a timeline of what each agent thought and
did. A module-level list, in the same single-process-per-run spirit as
memory.py's _id_counter.

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

_events: list = []
_started_at: str = None
_agents: list = []
_meta: dict = {}


def start(agents: list, meta: dict = None):
    """Reset the log for a fresh run. `agents` should be a list of dicts
    (name/color/etc, see main.py) so the viewer can build a legend before
    any events arrive."""
    global _events, _started_at, _agents, _meta
    _events = []
    _started_at = datetime.datetime.now().isoformat()
    _agents = agents
    _meta = meta or {}


def log(kind: str, tick: int, agent: str = None, **fields):
    """Append one structured event."""
    _events.append({"kind": kind, "tick": tick, "agent": agent, **fields})


def save(path: str = "run_log.json") -> str:
    """Write the whole run (agents, meta, events so far) to `path`."""
    payload = {
        "started_at": _started_at,
        "agents": _agents,
        "meta": _meta,
        "events": _events,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path
