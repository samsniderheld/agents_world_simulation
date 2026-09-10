"""The one persisted "active city" record -- history's generated payload
(eras/figures/places/events/map/summary/characters) plus everything hung
off it afterward (per-entity media, agent-simulation runs). Deliberately
its own small package rather than living inside history/ or agents/:
both write to it, so putting it in either would create a dependency in
the wrong direction.

This module is the *only* place that dict lives, in memory or on disk --
history/jobs.py used to hold its own in-process copy; now it just calls
get()/replace() here, so there's never a second copy to fall out of sync
with what a character/place-media attachment or an agent run appends.

Single active city (not a library of saved ones, see the project's
persistence plan): generating a new history replaces this outright.
"""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_STATE_PATH = _DATA_DIR / "city.json"

_lock = threading.Lock()
_cache = None       # the active city dict once loaded this process, or None
_loaded = False      # whether we've attempted the one lazy disk read yet


def _read_from_disk():
    global _cache, _loaded
    _loaded = True
    if _STATE_PATH.exists():
        with open(_STATE_PATH) as f:
            _cache = json.load(f)


def _write_to_disk(payload: dict):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    tmp.replace(_STATE_PATH)  # atomic on POSIX -- no half-written city.json


def get() -> dict:
    """The active city dict, or None if nothing's been generated yet (in
    this process, or ever, on disk). Loads from disk at most once per
    process -- this lazy read (rather than an explicit startup hydration
    call) is what makes a server restart transparently pick the city back
    up."""
    with _lock:
        if not _loaded:
            _read_from_disk()
        return _cache


def replace(history_payload: dict):
    """A new history finished generating -- this becomes the active city,
    wholesale. Fresh empty media/agent_runs: they belonged to whatever
    city this is replacing."""
    global _cache
    payload = dict(history_payload)
    payload["media"] = {}
    payload["agent_runs"] = []
    with _lock:
        _cache = payload
        _write_to_disk(payload)


def add_media(entity_id: str, kind: str, url: str, local_path: str = "", prompt: str = "") -> list:
    """Appends one media record to `entity_id`'s list and returns that
    updated list. Raises if there's no active city -- callers only reach
    this from a card that's already rendering a real entity."""
    record = {
        "id": f"media_{uuid.uuid4().hex[:8]}", "kind": kind, "url": url,
        "local_path": local_path, "prompt": prompt,
        "created_at": datetime.now().isoformat(),
    }
    with _lock:
        if not _loaded:
            _read_from_disk()
        if _cache is None:
            raise RuntimeError("no active city to attach media to")
        media = _cache.setdefault("media", {})
        media.setdefault(entity_id, []).append(record)
        _write_to_disk(_cache)
        return list(media[entity_id])


def remove_media(entity_id: str, media_id: str) -> bool:
    with _lock:
        if not _loaded:
            _read_from_disk()
        if _cache is None:
            return False
        items = _cache.get("media", {}).get(entity_id, [])
        kept = [m for m in items if m["id"] != media_id]
        if len(kept) == len(items):
            return False
        _cache["media"][entity_id] = kept
        _write_to_disk(_cache)
        return True


def append_agent_run(run_record: dict):
    """Quietly does nothing if there's no active city yet -- an agent run
    against the hardcoded noir cast (no generated history at all) has
    nowhere to attach to, and that's fine."""
    with _lock:
        if not _loaded:
            _read_from_disk()
        if _cache is None:
            return
        _cache.setdefault("agent_runs", []).append(run_record)
        _write_to_disk(_cache)
