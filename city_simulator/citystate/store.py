"""The persisted city collection -- one "active" city at a time is what
every other module actually reads/writes, split across separate files so
each thing is easy to find on disk instead of one growing JSON blob:

    citystate/data/
      active_city              -- a plain text file holding one city_id
      cities/<city_id>/
        city.json                 -- eras, figures, events, summary, generated_at
        locations.json            -- every place (each with its own embedded "media" list)
        locations/<id>/media/     -- that place's own image/video files
        agents/<id>/
          agent.json              -- the character record + "media", "plans", "runs"
          media/                  -- that agent's own image/video files

An "agent" and a "character" are the same identity here -- see
agents/simulation.py's roster_from_history(), which builds the agent
roster directly from a city's characters. So there's one file per person,
created the moment history generates their character, enriched with
plans/runs as simulations happen to them later.

The public API most callers use (get/get_agent/replace/delete/add_media/
remove_media/add_character/append_agent_run/add_treatment) is unchanged
from the single-city version on purpose: history/jobs.py, agents/
simulation.py, and every routes.py file all call through this module
implicitly against "the active city" and none of them need to change --
switching which city is active (list_cities()/set_active(), used only by
history/routes.py's new /api/history/cities* endpoints) is what makes the
node-based UI's per-city canvases work without touching agents/ or
visuals/ at all. get() still returns one composed dict shaped exactly
like the old city.json ({...history fields, "places": [...], "characters":
[...], "media": {...}}), so /api/history/data and every frontend reader
of it need zero changes either -- only how that dict gets produced and
persisted, and that there can be more than one, changes.

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
_CITIES_DIR = DATA_DIR / "cities"
_ACTIVE_FILE = DATA_DIR / "active_city"

_lock = threading.Lock()
_cache = None        # the composed *active* city dict once loaded this process, or None
_loaded = False       # whether we've attempted the one lazy disk read yet
_active_id = None     # the active city's id, or None if there isn't one


def _city_dir(city_id: str) -> Path:
    return _CITIES_DIR / city_id


def _history_path(city_id: str) -> Path:
    return _city_dir(city_id) / "city.json"


def _locations_path(city_id: str) -> Path:
    return _city_dir(city_id) / "locations.json"


def _agents_dir(city_id: str) -> Path:
    return _city_dir(city_id) / "agents"


def _locations_dir(city_id: str) -> Path:
    return _city_dir(city_id) / "locations"


def _is_location(entity_id: str) -> bool:
    return entity_id.startswith("place_")


def _agent_path(city_id: str, agent_id: str) -> Path:
    return _agents_dir(city_id) / agent_id / "agent.json"


def _agent_media_dir(city_id: str, agent_id: str) -> Path:
    return _agents_dir(city_id) / agent_id / "media"


def _location_media_dir(city_id: str, place_id: str) -> Path:
    return _locations_dir(city_id) / place_id / "media"


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    tmp.replace(path)  # atomic on POSIX -- no half-written file


def _read_active_id() -> str:
    if not _ACTIVE_FILE.exists():
        return None
    text = _ACTIVE_FILE.read_text().strip()
    return text or None


def _write_active_id(city_id: str) -> None:
    if city_id is None:
        _ACTIVE_FILE.unlink(missing_ok=True)
        return
    _ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ACTIVE_FILE.with_suffix(".tmp")
    tmp.write_text(city_id)
    tmp.replace(_ACTIVE_FILE)  # atomic on POSIX, same technique as _atomic_write


def _read_city_from_disk(city_id: str) -> dict:
    """Composes one city's full dict straight off disk -- the same shape
    _cache holds, but callable for any city, not just the active one
    (list_cities() uses the lighter city.json-only read instead; this
    full read is only for the active city, via _load_active())."""
    with open(_history_path(city_id)) as f:
        history = json.load(f)

    places = []
    if _locations_path(city_id).exists():
        with open(_locations_path(city_id)) as f:
            places = json.load(f)

    characters = []
    media = {}
    agents_dir = _agents_dir(city_id)
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            path = agent_dir / "agent.json"
            if not path.exists():
                continue
            with open(path) as f:
                agent = json.load(f)
            media[agent["id"]] = agent.get("media", [])
            characters.append({k: v for k, v in agent.items() if k not in ("media", "plans", "runs", "treatments")})

    for place in places:
        media[place["id"]] = place.get("media", [])

    return {**history, "places": places, "characters": characters, "media": media}


def _load_active() -> None:
    global _cache, _loaded, _active_id
    _loaded = True
    _active_id = _read_active_id()
    if _active_id is None or not _history_path(_active_id).exists():
        _cache = None
        return
    _cache = _read_city_from_disk(_active_id)


def _write_history(city_id: str) -> None:
    payload = {k: v for k, v in _cache.items() if k not in ("places", "characters", "media")}
    _atomic_write(_history_path(city_id), payload)


def _write_locations(city_id: str) -> None:
    places = []
    for place in _cache["places"]:
        place = dict(place)
        place["media"] = _cache["media"].get(place["id"], [])
        places.append(place)
    _atomic_write(_locations_path(city_id), places)


def _write_agent(city_id: str, agent_id: str, character: dict = None) -> None:
    """Read-modify-write of just this one agent's file -- plans/runs/
    treatments live only on disk (not in the in-memory _cache), so a
    media-only update has to preserve whatever's already there."""
    if character is None:
        character = next((c for c in _cache["characters"] if c["id"] == agent_id), None)
    if character is None:
        raise RuntimeError(f"unknown agent entity: {agent_id!r}")

    path = _agent_path(city_id, agent_id)
    existing = {}
    if path.exists():
        with open(path) as f:
            existing = json.load(f)

    payload = {
        **character,
        "media": _cache["media"].get(agent_id, []),
        "plans": existing.get("plans", []),
        "runs": existing.get("runs", []),
        "treatments": existing.get("treatments", []),
    }
    _atomic_write(path, payload)


def get() -> dict:
    """The active city dict, or None if there isn't one (in this process,
    or ever, on disk). Loads from disk at most once per process -- this
    lazy read (rather than an explicit startup hydration call) is what
    makes a server restart transparently pick the active city back up."""
    with _lock:
        if not _loaded:
            _load_active()
        return _cache


def get_agent(agent_id: str) -> dict:
    """One agent's full on-disk record (character bio + media + plans +
    runs) from the *active* city, read fresh -- not the in-memory _cache,
    since plans/runs only ever live on disk. None if no such agent (or no
    active city)."""
    with _lock:
        if not _loaded:
            _load_active()
        if _active_id is None:
            return None
    path = _agent_path(_active_id, agent_id)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _new_city_id() -> str:
    return f"city_{uuid.uuid4().hex[:8]}"


def _write_full_city(city_id: str, history_payload: dict) -> None:
    payload = dict(history_payload)
    places = payload.pop("places", [])
    characters = payload.pop("characters", [])
    payload.pop("media", None)
    payload.pop("agent_runs", None)  # no longer a top-level key -- see module docstring

    global _cache
    _cache = {**payload, "places": places, "characters": characters, "media": {}}
    _write_history(city_id)
    _write_locations(city_id)
    for character in characters:
        _write_agent(city_id, character["id"], character=character)


def replace(history_payload: dict, city_id: str = None) -> str:
    """A new history finished generating. With `city_id` (an existing
    city): regenerates that city in place, wiping its previous agents/
    locations directories (media included) -- the "regenerate" case, one
    of possibly several cities in the collection. Without it: creates a
    brand new city and makes it the active one -- the ordinary "Generate"
    case. Either way, returns the resulting city's id.

    Deliberately NOT touching graph_store here even on an in-place
    regenerate. A regenerate mints fresh char_*/place_* ids, so the
    previous city's nodes will reconcile as "missing" (dangling
    references) the next time the frontend loads it -- exactly the case
    reconciliation exists for (see graph_store.py's docstring and the
    frontend's reconcile.ts: "never auto-delete a node the user
    positioned"). Regenerating is a normal, frequent iteration action,
    not a "start over" -- wiping the user's whole canvas arrangement
    every time they re-roll a history would defeat the point of
    persisting it at all."""
    with _lock:
        target_id = city_id or _new_city_id()
        if _agents_dir(target_id).exists():
            shutil.rmtree(_agents_dir(target_id))
        if _locations_dir(target_id).exists():
            shutil.rmtree(_locations_dir(target_id))

        _write_full_city(target_id, history_payload)
        _write_active_id(target_id)
        global _active_id, _loaded
        _active_id = target_id
        _loaded = True
        return target_id


def list_cities() -> list:
    """Lightweight summaries for the top-level city picker -- reads just
    city.json plus cheap counts, never hydrates every agent file the way
    get()/_read_city_from_disk() does for the active city."""
    if not _CITIES_DIR.exists():
        return []
    active_id = get_active_id()
    summaries = []
    for city_dir in sorted(_CITIES_DIR.iterdir()):
        history_path = city_dir / "city.json"
        if not history_path.exists():
            continue
        with open(history_path) as f:
            history = json.load(f)
        locations_path = city_dir / "locations.json"
        place_count = 0
        if locations_path.exists():
            with open(locations_path) as f:
                place_count = len(json.load(f))
        agents_dir = city_dir / "agents"
        character_count = len([d for d in agents_dir.iterdir() if (d / "agent.json").exists()]) if agents_dir.exists() else 0
        summaries.append({
            "id": city_dir.name,
            "generated_at": history.get("generated_at"),
            "summary": history.get("summary", ""),
            "figure_count": len(history.get("figures", [])),
            "place_count": place_count,
            "character_count": character_count,
            "is_active": city_dir.name == active_id,
        })
    return summaries


def get_active_id() -> str:
    with _lock:
        if not _loaded:
            _load_active()
        return _active_id


def set_active(city_id: str) -> None:
    """Switches which city every other implicit-active-city call
    operates on. Raises if `city_id` isn't a real city -- callers only
    reach this from a real city tile that's already rendering, so a
    missing directory means something's out of sync and should be loud."""
    global _active_id, _cache, _loaded
    with _lock:
        if not _history_path(city_id).exists():
            raise RuntimeError(f"unknown city: {city_id!r}")
        _write_active_id(city_id)
        _active_id = city_id
        _cache = _read_city_from_disk(city_id)
        _loaded = True


def delete_city(city_id: str) -> None:
    """Removes one city from the collection outright -- if it happened to
    be the active city, there's no active city left afterward (the next
    get() returns None)."""
    global _cache, _active_id
    with _lock:
        if _city_dir(city_id).exists():
            shutil.rmtree(_city_dir(city_id))
        if _active_id == city_id or _read_active_id() == city_id:
            _write_active_id(None)
            _active_id = None
            _cache = None


def add_media(entity_id: str, kind: str, url: str, local_path: str = "", prompt: str = "", tag: str = "") -> list:
    """Relocates the file at `local_path` (wherever the fal/local provider
    originally saved it, typically visuals/data/outputs/) into this
    entity's own media/ directory (under the *active* city), appends the
    record, and returns the entity's updated media list. Raises if
    there's no active city, or if `entity_id` matches neither a known
    place nor agent -- callers only reach this from a card/modal that's
    already rendering a real entity, so either failure means something's
    out of sync and should be loud rather than silently dropping the
    write.

    `tag` is free-form ("exterior"/"interior" for a place, empty for
    everything else) -- the place modal picks its Exterior/Interior boxes
    by matching this, but any other tag (or none) still shows up in the
    entity's regular media strip."""
    with _lock:
        if not _loaded:
            _load_active()
        if _cache is None:
            raise RuntimeError("no active city to attach media to")
        city_id = _active_id

        is_location = _is_location(entity_id)
        dest_dir = _location_media_dir(city_id, entity_id) if is_location else _agent_media_dir(city_id, entity_id)
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
            _write_locations(city_id)
        else:
            _write_agent(city_id, entity_id)
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
            _load_active()
        if _cache is None:
            return False
        city_id = _active_id
        items = _cache["media"].get(entity_id, [])
        match = next((m for m in items if m["id"] == media_id), None)
        if match is None:
            return False
        items.remove(match)
        if match.get("local_path"):
            Path(match["local_path"]).unlink(missing_ok=True)

        if _is_location(entity_id):
            _write_locations(city_id)
        else:
            _write_agent(city_id, entity_id)
        return True


def add_character(character: dict) -> dict:
    """Adds one new character (and its matching agents/<id>/agent.json) to
    the active city -- for on-demand generation after history already
    exists (history/routes.py's POST /api/history/characters), as opposed
    to replace()'s initial batch at history-generation time. Raises if
    there's no active city yet -- a character needs a city to belong to."""
    with _lock:
        if not _loaded:
            _load_active()
        if _cache is None:
            raise RuntimeError("no active city to add a character to")
        _cache["characters"].append(character)
        _cache["media"].setdefault(character["id"], [])
        _write_agent(_active_id, character["id"], character=character)
        return character


def append_agent_run(run_record: dict) -> None:
    """Splits `run_record`'s events per agent and patches each
    participating agent's own agent.json (their "runs" list gains this
    run's own event slice; their "plans" list gains any "plan"-kind events
    from it). Quietly does nothing if there's no active city -- an agent
    run against the hardcoded noir cast has nowhere to persist to, and
    that's fine (matches the pre-split behavior)."""
    with _lock:
        if not _loaded:
            _load_active()
        if _cache is None:
            return
        city_id = _active_id

        name_to_id = {c["name"]: c["id"] for c in _cache["characters"]}
        events = run_record.get("events", [])
        for agent_meta in run_record.get("agents", []):
            agent_id = name_to_id.get(agent_meta["name"])
            path = _agent_path(city_id, agent_id) if agent_id else None
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


def add_treatment(agent_id: str, text: str, run_started_at: str = None) -> dict:
    """Appends one generated treatment to an agent's own persisted record
    (in the active city -- see agents/treatment.py, generated manually,
    per agent, from that agent's modal, not automatically per run).
    Direct read-modify-write of just this one file, same shape as
    append_agent_run() above, since treatments -- like plans/runs -- live
    only on disk, never in the in-memory _cache. Raises if the agent file
    doesn't exist."""
    with _lock:
        if not _loaded:
            _load_active()
        if _active_id is None:
            raise RuntimeError(f"unknown agent entity: {agent_id!r}")
        path = _agent_path(_active_id, agent_id)
        if not path.exists():
            raise RuntimeError(f"unknown agent entity: {agent_id!r}")

        with open(path) as f:
            data = json.load(f)

        entry = {
            "created_at": datetime.now().isoformat(),
            "run_started_at": run_started_at,
            "text": text,
        }
        data.setdefault("treatments", []).append(entry)
        _atomic_write(path, data)
        return entry
