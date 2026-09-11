"""The one persisted "active city" record, split across separate files so
each thing is easy to find on disk instead of one growing JSON blob:

    citystate/data/
      history.json          -- eras, figures, events, map, summary, generated_at
      locations.json        -- every place (each with its own embedded "media" list)
      locations/<id>/media/ -- that place's own image/video files
      agents/<id>/
        agent.json          -- the character record + "media", "plans", "runs"
        media/              -- that agent's own image/video files

An "agent" and a "character" are the same identity here -- see
agents/simulation.py's roster_from_history(), which builds the agent
roster directly from a city's characters. So there's one file per person,
created the moment history generates their character, enriched with
plans/runs as simulations happen to them later.

The public API (get/replace/add_media/remove_media/append_agent_run) is
unchanged from the single-blob version on purpose: history/jobs.py,
agents/simulation.py, and app.py all call through this module and none of
them need to change. get() still returns one composed dict shaped exactly
like the old city.json ({...history fields, "places": [...], "characters":
[...], "media": {...}}), so /api/history/data and every frontend file that
reads it need zero changes either -- only how that dict gets produced and
persisted changes.

Deliberately its own small package rather than living inside history/ or
agents/: both write to it, so putting it in either would create a
dependency in the wrong direction.
"""

import json
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
_HISTORY_PATH = DATA_DIR / "history.json"
_LOCATIONS_PATH = DATA_DIR / "locations.json"
_AGENTS_DIR = DATA_DIR / "agents"
_LOCATIONS_DIR = DATA_DIR / "locations"

_lock = threading.Lock()
_cache = None       # the composed active-city dict once loaded this process, or None
_loaded = False      # whether we've attempted the one lazy disk read yet


def _is_location(entity_id: str) -> bool:
    return entity_id.startswith("place_")


def _agent_path(agent_id: str) -> Path:
    return _AGENTS_DIR / agent_id / "agent.json"


def _agent_media_dir(agent_id: str) -> Path:
    return _AGENTS_DIR / agent_id / "media"


def _location_media_dir(place_id: str) -> Path:
    return _LOCATIONS_DIR / place_id / "media"


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    tmp.replace(path)  # atomic on POSIX -- no half-written file


def _read_from_disk() -> None:
    global _cache, _loaded
    _loaded = True
    if not _HISTORY_PATH.exists():
        return

    with open(_HISTORY_PATH) as f:
        history = json.load(f)

    places = []
    if _LOCATIONS_PATH.exists():
        with open(_LOCATIONS_PATH) as f:
            places = json.load(f)

    characters = []
    media = {}
    if _AGENTS_DIR.exists():
        for agent_dir in sorted(_AGENTS_DIR.iterdir()):
            path = agent_dir / "agent.json"
            if not path.exists():
                continue
            with open(path) as f:
                agent = json.load(f)
            media[agent["id"]] = agent.get("media", [])
            characters.append({k: v for k, v in agent.items() if k not in ("media", "plans", "runs")})

    for place in places:
        media[place["id"]] = place.get("media", [])

    _cache = {**history, "places": places, "characters": characters, "media": media}


def _write_history() -> None:
    payload = {k: v for k, v in _cache.items() if k not in ("places", "characters", "media")}
    _atomic_write(_HISTORY_PATH, payload)


def _write_locations() -> None:
    places = []
    for place in _cache["places"]:
        place = dict(place)
        place["media"] = _cache["media"].get(place["id"], [])
        places.append(place)
    _atomic_write(_LOCATIONS_PATH, places)


def _write_agent(agent_id: str, character: dict = None) -> None:
    """Read-modify-write of just this one agent's file -- plans/runs live
    only on disk (not in the in-memory _cache), so a media-only update
    has to preserve whatever's already there."""
    if character is None:
        character = next((c for c in _cache["characters"] if c["id"] == agent_id), None)
    if character is None:
        raise RuntimeError(f"unknown agent entity: {agent_id!r}")

    path = _agent_path(agent_id)
    existing = {}
    if path.exists():
        with open(path) as f:
            existing = json.load(f)

    payload = {
        **character,
        "media": _cache["media"].get(agent_id, []),
        "plans": existing.get("plans", []),
        "runs": existing.get("runs", []),
    }
    _atomic_write(path, payload)


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


def get_agent(agent_id: str) -> dict:
    """One agent's full on-disk record (character bio + media + plans +
    runs), read fresh -- not the in-memory _cache, since plans/runs only
    ever live on disk. None if no such agent."""
    path = _agent_path(agent_id)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def replace(history_payload: dict) -> None:
    """A new history finished generating -- this becomes the active city,
    wholesale. Wipes the previous city's agents/locations directories
    (media included) and writes fresh history.json/locations.json/one
    agent.json per character, all with empty plans/runs."""
    global _cache
    payload = dict(history_payload)
    places = payload.pop("places", [])
    characters = payload.pop("characters", [])
    payload.pop("media", None)
    payload.pop("agent_runs", None)  # no longer a top-level key -- see module docstring

    with _lock:
        if _AGENTS_DIR.exists():
            shutil.rmtree(_AGENTS_DIR)
        if _LOCATIONS_DIR.exists():
            shutil.rmtree(_LOCATIONS_DIR)

        _cache = {**payload, "places": places, "characters": characters, "media": {}}
        _write_history()
        _write_locations()
        for character in characters:
            _write_agent(character["id"], character=character)


def add_media(entity_id: str, kind: str, url: str, local_path: str = "", prompt: str = "", tag: str = "") -> list:
    """Relocates the file at `local_path` (wherever the fal/local provider
    originally saved it, typically visuals/data/outputs/) into this
    entity's own media/ directory, appends the record, and returns the
    entity's updated media list. Raises if there's no active city, or if
    `entity_id` matches neither a known place nor agent -- callers only
    reach this from a card/modal that's already rendering a real entity,
    so either failure means something's out of sync and should be loud
    rather than silently dropping the write.

    `tag` is free-form ("exterior"/"interior" for a place, empty for
    everything else) -- the place modal picks its Exterior/Interior boxes
    by matching this, but any other tag (or none) still shows up in the
    entity's regular media strip."""
    with _lock:
        if not _loaded:
            _read_from_disk()
        if _cache is None:
            raise RuntimeError("no active city to attach media to")

        is_location = _is_location(entity_id)
        dest_dir = _location_media_dir(entity_id) if is_location else _agent_media_dir(entity_id)
        new_local_path, new_url = _relocate_media_file(local_path, dest_dir) if local_path else (local_path, url)

        record = {
            "id": f"media_{uuid.uuid4().hex[:8]}", "kind": kind, "url": new_url,
            "local_path": new_local_path, "prompt": prompt, "tag": tag,
            "created_at": datetime.now().isoformat(),
        }
        media_list = _cache["media"].setdefault(entity_id, [])
        media_list.append(record)

        if is_location:
            if not any(p["id"] == entity_id for p in _cache["places"]):
                raise RuntimeError(f"unknown location entity: {entity_id!r}")
            _write_locations()
        else:
            _write_agent(entity_id)
        return list(media_list)


def _relocate_media_file(local_path: str, dest_dir: Path):
    """Moves the file into the entity's own media/ directory, returning
    its new (local_path, url). If the source is already gone (shouldn't
    happen), falls back to keeping local_path as the url too, rather than
    losing the reference entirely."""
    src = Path(local_path)
    if not src.exists():
        return local_path, local_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.move(str(src), str(dest))
    return str(dest), str(dest.relative_to(DATA_DIR))


def remove_media(entity_id: str, media_id: str) -> bool:
    with _lock:
        if not _loaded:
            _read_from_disk()
        if _cache is None:
            return False
        items = _cache["media"].get(entity_id, [])
        match = next((m for m in items if m["id"] == media_id), None)
        if match is None:
            return False
        items.remove(match)
        if match.get("local_path"):
            Path(match["local_path"]).unlink(missing_ok=True)

        if _is_location(entity_id):
            _write_locations()
        else:
            _write_agent(entity_id)
        return True


def append_agent_run(run_record: dict) -> None:
    """Splits `run_record`'s events per agent and patches each
    participating agent's own agent.json (their "runs" list gains this
    run's own event slice; their "plans" list gains any "plan"-kind events
    from it). Quietly does nothing if there's no active city -- an agent
    run against the hardcoded noir cast has nowhere to persist to, and
    that's fine (matches the pre-split behavior)."""
    with _lock:
        if not _loaded:
            _read_from_disk()
        if _cache is None:
            return

        name_to_id = {c["name"]: c["id"] for c in _cache["characters"]}
        events = run_record.get("events", [])
        for agent_meta in run_record.get("agents", []):
            agent_id = name_to_id.get(agent_meta["name"])
            path = _agent_path(agent_id) if agent_id else None
            if not agent_id or not path.exists():
                continue  # not one of this city's characters -- nothing to attach to

            with open(path) as f:
                data = json.load(f)

            agent_events = [e for e in events if e.get("agent") == agent_meta["name"]]
            data.setdefault("runs", []).append({
                "started_at": run_record.get("started_at"),
                "meta": run_record.get("meta", {}),
                "events": agent_events,
            })
            data.setdefault("plans", []).extend(
                {"run_started_at": run_record.get("started_at"), "tick": e.get("tick"), "items": e.get("items", [])}
                for e in agent_events if e.get("kind") == "plan"
            )
            _atomic_write(path, data)
