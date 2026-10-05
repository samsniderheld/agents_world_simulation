"""One shape for anyone in a city -- a hero (a saved character, `char_*`) or
a CITY background resident (`bg_*`) -- for the character page and the
canvas drawer (GET /api/agents/people/<id>). Everyone gets the same
sections; a resident's are simply thinner (no plans, run log, treatments
or media), and a resident who has been made a hero *is* that hero.

    {"id", "kind": "hero" | "resident", "name", "age", "occupation",
     "quirk", "bio", "places": [{"role", "place"}], "life": [{"year", "text"}],
     "sheet": {...}, "plans": [...], "memories": [...], "people": [...],
     "last_city_run": {...} | None, "runs": [...], "treatments": [...],
     "media": [...], "resident_id", "can_make_hero"}

Everything is newest first.
"""

import collections
import re

from .city import run as city_run
from .city import zoom
from .dm import stats as dm_stats
from .dm.sheet import attitude_label

_CLOCK_PREFIX = re.compile(r"^(Day \d+, )?\d{1,2}:\d{2}( [AP]M)?: ")
MAX_MEMORIES = 300
# Events the run log leaves out: memories have their own section, and these
# are bookkeeping rather than something the person did.
_LOG_SKIP = {"memory", "metrics", "status", "reflect_pause"}


def person(person_id: str, sheet_json=lambda s: s.to_dict()) -> dict:
    """`sheet_json` turns a CharacterSheet into what the page shows
    (routes.py's _sheet_json). Raises ValueError for an unknown id."""
    storage = city_run.storage
    resident = next((r for r in storage.get_background() or [] if r.get("id") == person_id), None)
    if resident is not None:
        hero_id = resident.get("promoted_to")
        if hero_id and storage.get_agent(hero_id) is not None:
            out = person(hero_id, sheet_json)
            out["resident_id"] = person_id
            return out
        return _resident(resident, sheet_json)
    record = storage.get_agent(person_id)
    character = next((c for c in (storage.get() or {}).get("characters", []) if c.get("id") == person_id), None)
    if record is None and character is None:
        raise ValueError(f"no such person: {person_id!r}")
    # agent.json holds the character too; the city's entry fills any gap
    return _hero(person_id, {**(character or {}), **(record or {})}, sheet_json)


def _ids_by_name() -> dict:
    """name -> id, for linking the people someone deals with to their pages."""
    storage = city_run.storage
    ids = {r["name"]: r["id"] for r in storage.get_background() or [] if not r.get("promoted_to")}
    ids.update({c["name"]: c["id"] for c in (storage.get() or {}).get("characters", [])})
    return ids


def _people(sheet, meetings: collections.Counter, heroes: set) -> list:
    """Everyone they feel something about or have dealt with: attitude
    (Dice & DM) first, then how often they met."""
    ids = _ids_by_name()
    names = set(meetings) | {n for n, v in sheet.relationships.items() if v}
    rows = [{"name": n, "id": ids.get(n), "hero": n in heroes or str(ids.get(n, "")).startswith("char_"),
             "meetings": meetings.get(n, 0), "attitude": sheet.attitude(n),
             "attitude_label": attitude_label(sheet.attitude(n))} for n in names]
    rows.sort(key=lambda r: (-abs(r["attitude"]), -r["meetings"], r["name"]))
    return rows[:40]


def _last_city_run(name: str):
    summary = city_run.storage.get_city_run()
    if not summary or name not in summary.get("agents", []):
        return None, summary
    return {"started_at": summary["started_at"], "stays": zoom.stays_for(summary, name)}, summary


def _hero(person_id: str, record: dict, sheet_json) -> dict:
    sheet = dm_stats.sheet_from_record(record, seed_key=person_id)
    memories, runs, meetings = [], [], collections.Counter()
    for run in reversed(record.get("runs") or []):
        meta = run.get("meta") or {}
        info = {"started_at": run.get("started_at"), "mode": meta.get("mode") or "scene", "dm": bool(meta.get("dm"))}
        events = []
        for e in run.get("events") or []:
            if e.get("kind") == "memory":
                memories.append({"time": zoom._clock(meta, e.get("tick", 0)), "kind": e.get("memory_kind"),
                                 "importance": e.get("importance"), "run_started_at": info["started_at"],
                                 "text": _CLOCK_PREFIX.sub("", e.get("text") or "")})
                continue
            if e.get("agent") == record["name"]:
                other = e.get("listener") or e.get("other") or e.get("opposed_by")
                if other and e.get("kind") in ("dialogue", "encounter", "check"):
                    meetings[other] += 1
            if e.get("kind") not in _LOG_SKIP:
                events.append({k: v for k, v in e.items() if k != "embedding"})
        runs.append({**info, "events": list(reversed(events))})
    # Within a run, newest memory first (runs are already newest first).
    by_run = collections.defaultdict(list)
    for m in memories:
        by_run[m["run_started_at"]].append(m)
    memories = [m for r in runs for m in reversed(by_run.get(r["started_at"], []))][:MAX_MEMORIES]

    last, summary = _last_city_run(record["name"])
    heroes = {h["name"] for h in (summary or {}).get("heroes", [])}
    place = record.get("place_name")
    return {
        "id": person_id, "kind": "hero", "name": record["name"], "age": record.get("age"),
        "occupation": record.get("occupation"), "quirk": record.get("quirk"), "bio": record.get("bio"),
        "places": [{"role": "at home in", "place": place}] if place else [],
        "life": [{"year": h.get("year"), "text": h.get("gospel_text")}
                 for h in sorted(record.get("history") or [], key=lambda h: h.get("year", 0), reverse=True)],
        "sheet": sheet_json(sheet),
        "plans": [{"run_started_at": p.get("run_started_at"), "tick": p.get("tick"), "items": p.get("items", [])}
                  for p in reversed(record.get("plans") or [])],
        "memories": memories,
        "people": _people(sheet, meetings, heroes),
        "last_city_run": last,
        "runs": runs,
        "treatments": list(reversed(record.get("treatments") or [])),
        "media": list(reversed(record.get("media") or [])),
        "resident_id": record.get("promoted_from"),
        "can_make_hero": False,
    }


def _resident(record: dict, sheet_json) -> dict:
    detail = zoom.resident_detail(record["id"])
    sheet = dm_stats.sheet_from_record(record, seed_key=record["id"])
    run = detail.get("run") or {}
    in_run = bool(run.get("in_run"))
    meetings = collections.Counter({a["name"]: a["count"] for a in run.get("acquaintances") or []})
    heroes = {a["name"] for a in run.get("acquaintances") or [] if a.get("hero")}
    places = [{"role": role, "place": record.get(key)} for role, key in
              (("works at", "work"), ("spends free time at", "haunt"), ("lives at", "home")) if record.get(key)]
    if not record.get("work"):
        places.insert(0, {"role": "works", "place": "off the map"})
    return {
        "id": record["id"], "kind": "resident", "name": record["name"], "age": record.get("age"),
        "occupation": record.get("occupation"), "quirk": None, "bio": record.get("bio"),
        "shift": record.get("shift"), "places": places, "life": [],
        "sheet": sheet_json(sheet), "plans": [],
        "memories": [{**m, "importance": None, "run_started_at": run.get("started_at")}
                     for m in reversed(run.get("memories") or [])] if in_run else [],
        "people": _people(sheet, meetings, heroes),
        "last_city_run": {"started_at": run["started_at"], "stays": run.get("stays") or [],
                          "hero_interactions": run.get("hero_interactions"), "schedule": run.get("schedule")}
        if in_run else None,
        "runs": [], "treatments": [], "media": [],
        "resident_id": record["id"], "can_make_hero": True,
    }
