"""The Population node's background job: pick N locations in the active
city and give each one a new resident who belongs there -- a character
grounded at that exact place (characters.generate_one's force_place_id: their
bio and life history come from its founder and recorded history) with a
square portrait -- plus a square exterior photo of the place if it doesn't
have one yet. Every resident and photo is generated in parallel (see
MAX_PARALLEL).

Locations aren't created -- a city's places come from its history. The
picks favor active places with no resident yet, then ones without an
exterior photo, newest first.

Two optional styles, from Style nodes wired into the node's two style
ports: one applied to every portrait, one to every exterior. A style is
applied exactly as it is for an Image or Frame node (visuals/routes.py):
its prompt joined onto the image prompt with ", ", its reference images
sent as input images (which switches fal to its edit model).

Images come from the active visuals provider called directly (not
through visuals/jobs.py's single slot, so this doesn't block or get blocked
by an Image/Frame node), requested square (aspect_ratio 1:1) at the model's
native 1024x1024. One job at a time; one failed item is logged and skipped
rather than aborting the batch.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from citystate import store as citystate
from visuals import providers as visual_providers

from . import characters

MAX_COUNT = 50
# How many characters/photos are worked on at once. Every step is a remote
# call (LLM + image API), so this is mostly waiting -- except with the local
# image provider, which runs on this machine's GPU and gets 1.
MAX_PARALLEL = 6

_lock = threading.Lock()
_thread: threading.Thread = None
_stop = threading.Event()
_status = {"phase": "idle", "error": None, "total": 0, "done": 0, "active": 0, "current": "", "log": []}


def _set(**fields):
    with _lock:
        _status.update(fields)


def _log(line: str):
    with _lock:
        _status["log"] = (_status["log"] + [line])[-200:]


def _square_image(prompt: str, style: dict = None):
    """Generate one square image and return (url, local_path, full prompt)."""
    style = style or {}
    prompt = ", ".join(p for p in (prompt, (style.get("prompt") or "").strip()) if p)
    refs = [r for r in (style.get("reference_images") or []) if r] or None
    result = visual_providers.get_provider().generate_image(prompt, refs, aspect_ratio="1:1")
    if not result.get("images"):
        raise RuntimeError("the image provider returned no image")
    image = result["images"][0]
    return image["url"], image["local_path"], prompt


def _portrait_prompt(c: dict) -> str:
    return (
        f"Head-and-shoulders portrait photograph of {c['name']}, a {c.get('age', 40)}-year-old "
        f"{c.get('occupation') or 'resident'} in New York City in the late 1950s. "
        f"{c.get('bio', '')} "
        "Facing the camera, plain neutral backdrop, natural light, period-accurate hair and "
        "clothing, realistic photograph, no text."
    )


def _exterior_prompt(p: dict, noun: str) -> str:
    return (
        f"Exterior photograph of {p['name']}, a {noun} in New York City, seen from the street "
        f"as it stands in the late 1950s. {p.get('architecture', '')} "
        "Realistic street-level photograph, the whole building facade in frame, no people "
        "blocking the view, no text or signage besides the establishment's own name."
    )


def _has_exterior(city: dict) -> set:
    return {
        entity_id for entity_id, items in (city.get("media") or {}).items()
        if any(m.get("kind") == "image" and m.get("tag") == "exterior" for m in items)
    }


def _pick_locations(city: dict, count: int) -> list:
    """Active places with no resident yet first, then ones without an
    exterior photo, newest first."""
    has_exterior = _has_exterior(city)
    has_resident = {c.get("place_id") for c in city.get("characters", [])}
    active = [p for p in city.get("places", []) if p.get("status") == "active"]
    active.sort(key=lambda p: (p["id"] in has_resident, p["id"] in has_exterior, -(p.get("founded_year") or 0)))
    return active[:count]


def _progress():
    with _lock:
        _status["done"] += 1
        _status["active"] -= 1
        _status["current"] = f"{_status['active']} in progress" if _status["active"] else ""


def _make_character(place: dict, style: dict, on_characters_added) -> bool:
    if _stop.is_set():
        return True
    with _lock:
        _status["active"] += 1
        _status["current"] = f"{_status['active']} in progress"
    try:
        city = citystate.get()
        character = characters.generate_one(
            [SimpleNamespace(**p) for p in city.get("places", [])],
            [SimpleNamespace(**f) for f in city.get("figures", [])],
            force_place_id=place["id"],
        )
        saved = citystate.add_character(character)
        on_characters_added()
        url, local, prompt = _square_image(_portrait_prompt(saved), style)
        citystate.add_media(saved["id"], "image", url, local_path=local, prompt=prompt, tag="portrait")
        _log(f"+ {saved['name']}, {saved.get('occupation') or 'resident'} at {place['name']}")
        return True
    except Exception as e:
        _log(f"! resident for {place['name']}: {e}")
        return False
    finally:
        _progress()


def _photograph(place: dict, style: dict) -> bool:
    from . import entities  # place-type nouns ("tavern", "brewery", ...)
    if _stop.is_set():
        return True
    with _lock:
        _status["active"] += 1
        _status["current"] = f"{_status['active']} in progress"
    try:
        noun = entities.PLACE_TYPE_NOUN.get(place.get("place_type"), "building")
        url, local, prompt = _square_image(_exterior_prompt(place, noun), style)
        citystate.add_media(place["id"], "image", url, local_path=local, prompt=prompt, tag="exterior")
        _log(f"+ exterior of {place['name']}")
        return True
    except Exception as e:
        _log(f"! {place['name']}: {e}")
        return False
    finally:
        _progress()


def _worker(count: int, on_characters_added, character_style: dict, location_style: dict):
    try:
        city = citystate.get()
        if city is None:
            raise RuntimeError("no active city -- generate one first")
        targets = _pick_locations(city, count)
        if not targets:
            raise RuntimeError("the city has no active locations")
        if len(targets) < count:
            _log(f"only {len(targets)} active location(s) available")
        needs_photo = [p for p in targets if p["id"] not in _has_exterior(city)]
        _set(total=len(targets) + len(needs_photo))

        from visuals import config as visuals_config
        parallel = 1 if visuals_config.PROVIDER == "local" else MAX_PARALLEL
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(_make_character, place, character_style, on_characters_added) for place in targets]
            futures += [pool.submit(_photograph, place, location_style) for place in needs_photo]
            errors = sum(not f.result() for f in futures)

        _set(phase="done", current="stopped" if _stop.is_set() else "",
             error=f"{errors} item(s) failed -- see the log" if errors else None)
    except Exception as e:
        _set(phase="error", error=str(e), current="")


def start(count: int, on_characters_added=lambda: None,
          character_style: dict = None, location_style: dict = None):
    """Returns (ok, error_message). `count` is how many locations get a new
    resident. `on_characters_added` runs after each saved character
    (routes.py uses it to refresh the agent roster). Each style is
    {"prompt": str, "reference_images": [paths]} or None."""
    global _thread
    count = max(0, min(MAX_COUNT, int(count)))
    if count == 0:
        return False, "nothing to do -- set how many locations to populate"
    with _lock:
        if _thread and _thread.is_alive():
            return False, "a population run is already in progress"
        _stop.clear()
        _status.update(phase="running", error=None, total=count, done=0, active=0, current="starting", log=[])
        _thread = threading.Thread(
            target=_worker, args=(count, on_characters_added, character_style, location_style), daemon=True,
        )
        _thread.start()
    return True, None


def stop():
    _stop.set()


def is_running() -> bool:
    with _lock:
        return bool(_thread and _thread.is_alive())


def get_status() -> dict:
    with _lock:
        return {**_status, "log": list(_status["log"])}
