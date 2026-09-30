"""Flask blueprint for the agent-simulation API -- thin view functions
that parse the request and delegate to jobs.py/simulation.py/recorder.py.
"""

import re

from flask import Blueprint, request

from citystate import store as citystate
from jsonutil import json_response

from . import jobs, providers, recorder, simulation, treatment
from .city import recorder as city_recorder

bp = Blueprint("agents", __name__, url_prefix="/api/agents")


@bp.get("/roster")
def roster():
    return json_response({"roster": simulation.roster_summary()})


@bp.get("/providers")
def provider_list():
    return json_response({"providers": providers.AVAILABLE_PROVIDERS})


@bp.get("/city/profiles")
def city_profiles():
    """CITY hardware profiles (hardware.py) for the City Simulation node's
    picker, and which one "auto" resolves to on this machine."""
    import hardware
    return json_response({
        "profiles": {name: hardware.city_profile(name) for name in hardware.CITY_PROFILES},
        "detected": hardware.detect_city_profile(),
    })


@bp.get("/models")
def models():
    provider = request.args.get("provider") or None
    try:
        return json_response({"models": providers.get_provider(provider).list_models()})
    except Exception as e:
        return json_response({"models": [], "error": str(e)})


@bp.get("/state")
def state():
    if jobs.current_mode() == "city":
        return json_response({"status": {**jobs.get_status(), "mode": "city"}, **city_recorder.state()})
    _, total = recorder.snapshot(0)
    return json_response({
        "status": jobs.get_status(),
        "agents": recorder.get_agents(),
        "meta": recorder.get_meta(),
        "started_at": recorder.get_started_at(),
        "event_count": total,
    })


@bp.get("/events")
def events():
    since = int(request.args.get("since", "0"))
    if jobs.current_mode() == "city":
        # `since` is a cursor (the last event's seq), not a list index.
        # Filters: tier=hero (default) | background | all, kinds=a,b,
        # agent=, place=, limit= (default 500).
        kinds = {k for k in (request.args.get("kinds") or "").split(",") if k} or None
        page = city_recorder.query(
            since, tier=request.args.get("tier") or "hero", kinds=kinds,
            agent=request.args.get("agent") or None, place=request.args.get("place") or None,
            limit=max(1, min(5000, int(request.args.get("limit") or 500))))
        return json_response(page)
    events, total = recorder.snapshot(since)
    return json_response({"events": events, "next": total})


def _opt_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _start_time(value):
    """Normalizes "7:30" / "07:30" to "07:30"; None for blank or invalid."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _convene_place_name(body):
    """The place name a Location wired into the node resolves to, None
    when there isn't one; raises ValueError for an unknown place id."""
    place_id = body.get("place_id")
    if not place_id or (body.get("location_mode") or "grounded") != "convene":
        return None
    city = citystate.get()
    place = next((p for p in (city or {}).get("places") or [] if p["id"] == place_id), None)
    if place is None:
        raise ValueError(f"no such place: {place_id!r}")
    return place["name"]


def _city_params(body):
    """The City Simulation node's run request -> agents.city.run.run()'s
    keyword arguments."""
    def opt_int(key, lo, hi):
        return max(lo, min(hi, int(body[key]))) if body.get(key) not in (None, "") else None
    return {
        "hero_names": body.get("agent_names") or None,
        "background_count": opt_int("background_count", 0, 5000) or 0,
        "profile": body.get("profile") or "auto",
        "hero_provider": body.get("hero_provider") or None,
        "hero_model": body.get("hero_model") or None,
        "background_provider": body.get("background_provider") or None,
        "background_model": body.get("background_model") or None,
        "ticks": opt_int("ticks", 1, 1000) or 8,
        "tick_minutes": opt_int("tick_minutes", 1, 1440),
        "start_time": _start_time(body.get("start_time")),
        "directive": (body.get("directive") or "").strip() or None,
        "convene_at": _convene_place_name(body),
        "persist_hero_memories": bool(body.get("persist_hero_memories", True)),
        "seed": opt_int("seed", 0, 2**31 - 1),
    }


@bp.post("/run")
def run():
    body = request.get_json(silent=True) or {}

    # "scene" (the default, and what every client sent before CITY mode
    # existed) or "city". Both share jobs.py's single slot.
    if (body.get("mode") or "scene") == "city":
        try:
            params = _city_params(body)
        except (ValueError, TypeError) as e:
            return json_response({"ok": False, "error": str(e)}, status=400)
        ok, error = jobs.start(params, mode="city")
        return json_response({"ok": ok, "error": error}, status=200 if ok else 409)

    # "convene" (the node-based UI's Location -> Simulation edge) makes
    # every selected agent start this run at `place_id` instead of their
    # own grounding place -- resolved to a place *name* here, since
    # world.py's co-presence check is plain location-string equality
    # (agents/world.py), not an id lookup. "grounded" (the default) leaves
    # each agent's own location untouched.
    place_id = body.get("place_id")
    location_mode = body.get("location_mode") or "grounded"
    convene_at = None
    if place_id and location_mode == "convene":
        city = citystate.get()
        place = next((p for p in (city or {}).get("places") or [] if p["id"] == place_id), None)
        if place is None:
            return json_response({"ok": False, "error": f"no such place: {place_id!r}"}, status=400)
        convene_at = place["name"]

    params = {
        "ticks": int(body.get("ticks", 8)),
        "provider": body.get("provider") or None,
        "tick_sleep": float(body.get("tick_sleep", 0)),
        "chat_model": body.get("chat_model") or None,
        "embed_model": body.get("embed_model") or None,
        "context_tokens": body.get("context_tokens") or None,
        "agent_names": body.get("agent_names") or None,
        "verbose": bool(body.get("verbose", False)),
        "convene_at": convene_at,
        # Simulation node's free-text "guide how the characters are
        # interacting" field -- see simulation.run()'s docstring.
        "directive": (body.get("directive") or "").strip() or None,
        # Simulated minutes per tick (the Simulation node's setting); blank
        # keeps config.TICK_MINUTES.
        "tick_minutes": max(1, min(1440, int(body["tick_minutes"]))) if body.get("tick_minutes") else None,
        # Simulated time of day the run starts at, "HH:MM" (24-hour);
        # blank = 06:00.
        "start_time": _start_time(body.get("start_time")),
    }
    ok, error = jobs.start(params)
    return json_response({"ok": ok, "error": error}, status=200 if ok else 409)


@bp.post("/stop")
def stop():
    jobs.stop()
    from .city import run as city_run
    city_run.pause_flag.clear()      # a paused CITY run has to wake up to see the stop
    return json_response({"ok": True})


# --- CITY-only controls -------------------------------------------------------

@bp.post("/city/pause")
def city_pause():
    from .city import run as city_run
    if jobs.current_mode() != "city" or jobs.get_status()["phase"] != "running":
        return json_response({"ok": False, "error": "no CITY run is in progress"}, status=409)
    city_run.pause_flag.set()
    city_recorder.set_meta(paused=True)
    return json_response({"ok": True})


@bp.post("/city/resume")
def city_resume():
    from .city import run as city_run
    city_run.pause_flag.clear()
    city_recorder.set_meta(paused=False)
    return json_response({"ok": True})


@bp.post("/city/promote")
def city_promote():
    """Promote a background resident of the running CITY run to hero (at
    the end of the current tick)."""
    from .city import run as city_run
    name = (request.get_json(silent=True) or {}).get("name")
    error = city_run.request_promotion(name) if name else "name is required"
    return json_response({"ok": error is None, "error": error}, status=200 if error is None else 400)


@bp.get("/city/runs")
def city_runs():
    return json_response({"runs": citystate.list_city_runs()})


@bp.get("/city/zoom")
def city_zoom_options():
    """Places and tick times a CITY run can be zoomed into (the live run
    while it's paused or just finished, else a saved one)."""
    from .city import zoom
    if jobs.current_mode() == "city" and jobs.get_status()["phase"] == "running" \
            and not city_recorder.state()["meta"].get("paused"):
        return json_response({"error": "pause or stop the CITY run to zoom in"}, status=409)
    found = zoom.options(request.args.get("started_at") or None)
    if found is None:
        return json_response({"error": "there's no CITY run to zoom into yet"}, status=404)
    return json_response(found)


@bp.post("/city/zoom")
def city_zoom():
    """Resolve a place + window of ticks in a CITY run into a SCENE run's
    cast, place and start time -- promoting background residents who were
    there to saved characters first (agents/city/zoom.py)."""
    from .city import zoom
    body = request.get_json(silent=True) or {}
    if not body.get("place"):
        return json_response({"error": "place is required"}, status=400)
    try:
        result = zoom.zoom(body["place"], int(body.get("tick_from", 0)), int(body.get("tick_to", 0)),
                           started_at=body.get("started_at") or None)
    except ValueError as e:
        return json_response({"error": str(e)}, status=400)
    if result["promoted"]:
        simulation.set_history_roster(citystate.get())   # SCENE's roster now includes them
    return json_response(result)


@bp.post("/treatment")
def generate_treatment_for_agent():
    """Generates (and persists) a treatment for one agent's most recent
    run -- triggered manually from a Treatment node, see
    treatment.build_transcript()'s docstring for why this needs every
    co-participant's own record, not just this agent's."""
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    record = citystate.get_agent(agent_id) if agent_id else None
    if record is None:
        return json_response({"error": "no such agent"}, status=404)
    runs = record.get("runs") or []
    if not runs:
        return json_response({"error": "this agent has no runs yet"}, status=400)

    city = citystate.get()
    if city is None:
        return json_response({"error": "no active city"}, status=404)

    latest = runs[-1]
    agent_records = {c["name"]: citystate.get_agent(c["id"]) for c in city.get("characters", [])}
    # A run without a mode predates CITY mode: it's a SCENE run.
    is_city = (latest.get("meta") or {}).get("mode", "scene") == "city"
    if is_city:
        # Heroes only (plus background lines said to them), optionally
        # narrowed to one place / window of ticks, so the prompt stays bounded.
        log, agent_names, locations = treatment.build_city_transcript(
            agent_records, latest.get("started_at"), place=body.get("place") or None,
            tick_from=_opt_int(body.get("tick_from")), tick_to=_opt_int(body.get("tick_to")))
    else:
        log, agent_names, locations = treatment.build_transcript(agent_records, latest.get("started_at"))

    # Resolve each bare location name build_transcript() found in the
    # transcript against its real place record, for its `architecture`
    # text -- an event only ever stores the place *name* (see recorder.py's
    # schema), so this is the one spot that can actually reach the visual
    # description treatment.generate_treatment() needs to stop inventing
    # scenery from the name alone. `place_ids` -- the Treatment node's own
    # place:in port (frontend/src/flow/nodes/TreatmentNode.tsx) -- adds any
    # place the user explicitly pointed at, even one the transcript itself
    # never visited, without duplicating one already found in the log.
    places_by_name = {p["name"]: p for p in city.get("places", []) if p.get("name")}
    places_by_id = {p["id"]: p for p in city.get("places", []) if p.get("id")}
    location_details = [
        {"name": name, "architecture": places_by_name[name].get("architecture", "")}
        for name in locations if name in places_by_name
    ]
    seen_place_names = {loc["name"] for loc in location_details}
    for place_id in body.get("place_ids") or []:
        place = places_by_id.get(place_id)
        if place and place.get("name") and place["name"] not in seen_place_names:
            location_details.append({"name": place["name"], "architecture": place.get("architecture", "")})
            seen_place_names.add(place["name"])

    # Same idea for cast -- every transcript participant's real bio (which
    # includes physical description/wardrobe, see history/characters.py),
    # plus `agent_ids` for any character the user explicitly wired in via
    # the Treatment node's agent:in port even if they don't appear in the
    # transcript at all (e.g. someone being described but not present).
    characters_by_name = {c["name"]: c for c in city.get("characters", []) if c.get("name")}
    characters_by_id = {c["id"]: c for c in city.get("characters", []) if c.get("id")}
    cast_details = [
        {"name": name, "bio": characters_by_name[name].get("bio", "")}
        for name in agent_names if name in characters_by_name
    ]
    if is_city:   # background residents who spoke: their one-line bios
        residents = {r["name"]: r for r in citystate.get_background()}
        cast_details += [{"name": n, "bio": residents[n].get("bio", "")}
                         for n in agent_names if n not in characters_by_name and n in residents]
    seen_cast_names = {c["name"] for c in cast_details}
    for extra_agent_id in body.get("agent_ids") or []:
        character = characters_by_id.get(extra_agent_id)
        if character and character.get("name") and character["name"] not in seen_cast_names:
            cast_details.append({"name": character["name"], "bio": character.get("bio", "")})
            seen_cast_names.add(character["name"])

    provider = body.get("provider") or None
    model = body.get("model") or None
    # The Simulation node's free-text directive for this run, if it had one
    # -- persisted in the run's meta (see simulation.run()), so the
    # treatment knows what the scene was *meant* to be about, not just
    # what the transcript happens to show.
    directive = (latest.get("meta") or {}).get("directive")
    text = treatment.generate_treatment(
        log, agent_names, model=model, provider=provider,
        location_details=location_details, cast_details=cast_details,
        directive=directive,
    )
    entry = citystate.add_treatment(agent_id, text, run_started_at=latest.get("started_at"))
    return json_response({"treatment": entry})


@bp.get("/treatment/shots")
def treatment_shots():
    """Parses the treatment text a Treatment node currently holds into its
    individual storyboard shots -- a query param, not
    tied to a stored treatment id, since treatment entries don't have one
    (see citystate.store.add_treatment's schema) and this needs to work
    for a just-generated treatment too, before any re-fetch from disk."""
    text = request.args.get("text", "")
    return json_response({"shots": treatment.parse_storyboard_shots(text)})
