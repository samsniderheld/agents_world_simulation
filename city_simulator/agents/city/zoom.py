"""Zoom in: from a finished or paused CITY run, pick a place and a window
of ticks, and get everything a SCENE run needs to replay that moment with
full cognition -- the people who were there, the place, the start time and
length.

Heroes are already saved characters. Background residents who were there
get promoted to saved characters first: a cheap LLM call upgrades their
one-line bio into a proper dossier (appearance and wardrobe included, like
every generated resident's), and their last few memories from the CITY run
are appended to their new record so SCENE's MemoryStream has something to
start from.

The data comes from the live run while it's in memory (paused or just
finished), otherwise from the run's saved summary (citystate city_runs/).
"""

import asyncio
import datetime

import hardware
from history import entities

from ..gateway import Gateway, LLMRequest, backends_for_profile
from . import config as ccfg
from . import prompts
from . import run as city_run
from .tiers import heuristic_importance

MAX_CAST = 8


def _source(started_at: str = None) -> dict:
    """The run summary to zoom into: the live run's, when it's the one
    asked for (or none was named), else the saved one."""
    world = city_run.current_world()
    if world is not None and world.tick > 0:
        live = city_run.run_summary(world)
        if started_at in (None, live["started_at"]):
            return live
    return city_run.storage.get_city_run(started_at)


def options(started_at: str = None) -> dict:
    """What the zoom picker offers: each on-map place with how many heroes
    and people were ever there, and the clock time of every tick."""
    summary = _source(started_at)
    if not summary:
        return None
    meta = summary["meta"]
    heroes = {h["name"] for h in summary["heroes"]}
    names = summary["agents"]
    places = summary["places"]
    city = city_run.storage.get() or {}
    on_map = {p["name"]: p["id"] for p in city.get("places", [])}
    counts = {}
    for tick in summary["positions"]:
        for i, place_index in enumerate(tick):
            if place_index < 0 or places[place_index] not in on_map:
                continue
            c = counts.setdefault(places[place_index], [set(), set()])
            c[0 if names[i] in heroes else 1].add(names[i])
    out = [{"name": p, "place_id": on_map[p], "heroes": len(c[0]), "people": len(c[0]) + len(c[1])}
           for p, c in counts.items()]
    out.sort(key=lambda x: (-x["heroes"], -x["people"], x["name"]))
    return {"started_at": summary["started_at"], "places": out, "ticks": len(summary["positions"]),
            "times": [_clock(meta, t) for t in range(len(summary["positions"]))],
            "tick_minutes": meta.get("tick_minutes"), "start_time": meta.get("start_time")}


def _clock(meta: dict, tick: int) -> str:
    """HH:MM of a tick, for SCENE's start_time (the day is dropped)."""
    hour, minute = (int(x) for x in (meta.get("start_time") or "06:00").split(":"))
    when = datetime.datetime(2026, 8, 24, hour, minute) + datetime.timedelta(minutes=(meta.get("tick_minutes") or 30) * tick)
    return when.strftime("%H:%M")


def cast_at(summary: dict, place: str, tick_from: int, tick_to: int, max_cast: int = MAX_CAST) -> list:
    """Who was at `place` during [tick_from, tick_to]: heroes first (most
    time there first), then background residents (most dealings with
    heroes, then most time there). [(name, is_hero, ticks present)]."""
    if place not in summary["places"]:
        return []
    target = summary["places"].index(place)
    presence = {}
    for tick in summary["positions"][tick_from:tick_to + 1]:
        for i, where in enumerate(tick):
            if where == target:
                presence[summary["agents"][i]] = presence.get(summary["agents"][i], 0) + 1
    hero_names = {h["name"] for h in summary["heroes"]}
    interactions = {b["name"]: b.get("hero_interactions", 0) for b in summary["background"].values()}
    heroes = sorted((n for n in presence if n in hero_names), key=lambda n: (-presence[n], n))
    others = sorted((n for n in presence if n not in hero_names),
                    key=lambda n: (-interactions.get(n, 0), -presence[n], n))
    return [(n, n in hero_names, presence[n]) for n in (heroes + others)[:max_cast]]


def zoom(place: str, tick_from: int, tick_to: int, started_at: str = None, transport=None) -> dict:
    """Resolve a zoom-in to a SCENE run's parameters, promoting any
    background residents in the cast to saved characters first."""
    summary = _source(started_at)
    if not summary:
        raise ValueError("there's no CITY run to zoom into yet")
    ticks = len(summary["positions"])
    tick_from = max(0, min(int(tick_from), ticks - 1))
    tick_to = max(tick_from, min(int(tick_to), ticks - 1))
    cast = cast_at(summary, place, tick_from, tick_to)
    if not cast:
        raise ValueError(f"nobody was at {place} between those times")
    city = city_run.storage.get() or {}
    characters = {c["name"]: c for c in city.get("characters", [])}
    places = {p["name"]: p for p in city.get("places", [])}
    residents = {r["name"]: r for r in city_run.storage.get_background()}
    recent = {b["name"]: b.get("recent", []) for b in summary["background"].values()}
    recent.update(summary.get("promoted_memories") or {})
    whereabouts = {n: _whereabouts(summary, n, place, tick_from, tick_to) for n, _, _ in cast}
    promoted_names = {h["name"]: h.get("promoted_from") for h in summary["heroes"] if h.get("promoted_from")}

    to_promote = []
    backfill = []
    for name, _, _ in cast:
        if name in characters:
            # Promoted by an earlier zoom but holding nothing from this run
            # yet: give them this run's memories now.
            c = characters[name]
            if c.get("promoted_from") and not _has_run(c["id"], summary["started_at"]):
                backfill.append(c)
            continue
        record = residents.get(name)
        if record is None and name in promoted_names:
            record = next((r for r in residents.values() if r["id"] == promoted_names[name]), None)
        if record is not None:
            to_promote.append(record)
    created = asyncio.run(_promote(to_promote, place, places, summary, recent, whereabouts, transport)) \
        if to_promote else []
    if backfill:
        asyncio.run(_backfill(backfill, summary, recent, whereabouts, transport))
    for c in created:
        characters[c["name"]] = c

    meta = summary["meta"]
    agent_names = [n for n, _, _ in cast if n in characters]
    return {
        "started_at": summary["started_at"],
        "place": place,
        "place_id": places.get(place, {}).get("id"),
        "tick_from": tick_from,
        "tick_to": tick_to,
        "start_time": _clock(meta, tick_from),
        "tick_minutes": meta.get("tick_minutes"),
        "ticks": tick_to - tick_from + 1,
        "directive": meta.get("directive"),
        "agent_names": agent_names,
        "agent_ids": [characters[n]["id"] for n in agent_names],
        "characters": created,
        "promoted": [c["name"] for c in created],
    }


def _has_run(character_id: str, started_at: str) -> bool:
    record = city_run.storage.get_agent(character_id) or {}
    return any(r.get("started_at") == started_at for r in record.get("runs", []))


def _whereabouts(summary: dict, name: str, place: str, tick_from: int, tick_to: int):
    """[tick, kind, text]: where this person was during the zoomed window,
    so even someone who met nobody remembers being there."""
    if name not in summary["agents"] or place not in summary["places"]:
        return None
    i, target = summary["agents"].index(name), summary["places"].index(place)
    ticks = [t for t in range(tick_from, tick_to + 1)
             if t < len(summary["positions"]) and summary["positions"][t][i] == target]
    if not ticks:
        return None
    meta = summary["meta"]
    return [ticks[0], "observation",
            f"{name} was at {place} from {_clock(meta, ticks[0])} to {_clock(meta, ticks[-1] + 1)}."]


async def _memory_events(gw, name: str, mems: list) -> list:
    vectors = await gw.embed_many([m[2] for m in mems])
    return [{"kind": "memory", "tick": tick, "agent": name,
             "memory_kind": "chat" if kind == "dialogue" else "observation",
             "importance": heuristic_importance(text, kind), "text": text,
             "embedding": [round(float(x), 6) for x in vector], "evidence": []}
            for (tick, kind, text), vector in zip(mems, vectors)]


def _save_memories(name: str, summary: dict, events: list):
    if events:
        city_run.storage.append_agent_run({
            "started_at": summary["started_at"], "meta": dict(summary["meta"], mode="city"),
            "agents": [{"name": name}], "events": [],
        }, slices={name: events})


def _memories_for(name: str, recent: dict, whereabouts: dict) -> list:
    mems = [list(m) for m in recent.get(name, [])]
    if whereabouts.get(name) and whereabouts[name][2] not in {m[2] for m in mems}:
        mems.append(whereabouts[name])
    return sorted(mems, key=lambda m: m[0])


async def _backfill(characters: list, summary: dict, recent: dict, whereabouts: dict, transport):
    meta = summary["meta"]
    profile = hardware.city_profile(meta.get("profile") or "auto")
    backends = backends_for_profile(profile, meta.get("provider"), meta.get("chat_model"),
                                    meta.get("background_provider"), meta.get("background_model"))
    async with Gateway(backends, transport=transport) as gw:
        for c in characters:
            _save_memories(c["name"], summary, await _memory_events(gw, c["name"], _memories_for(c["name"], recent, whereabouts)))


async def _promote(records: list, place: str, places: dict, summary: dict, recent: dict, whereabouts: dict,
                   transport) -> list:
    meta = summary["meta"]
    profile = hardware.city_profile(meta.get("profile") or "auto")
    backends = backends_for_profile(profile, meta.get("provider"), meta.get("chat_model"),
                                    meta.get("background_provider"), meta.get("background_model"))
    async with Gateway(backends, transport=transport) as gw:
        requests = [LLMRequest(agent=r["name"], tier="background",
                               prompt_parts=[prompts.city_prefix(city_run.storage.get()), prompts.BACKGROUND_TIER,
                                             f"{r['name']}, {r['age']}, {r['occupation']}.",
                                             prompts.bio_upgrade(_Resident(r), place)],
                               max_tokens=ccfg.TOKENS_BIO, temperature=0.9, kind="bio")
                    for r in records]
        results = await gw.generate_many(requests)
        memory_events = [await _memory_events(gw, r["name"], _memories_for(r["name"], recent, whereabouts))
                         for r in records]
    created = []
    for r, result, events in zip(records, results, memory_events):
        bio, quirk = _parse_bio(result.text if result.ok else "")
        home = places.get(r.get("work")) or places.get(r.get("haunt")) or places.get(place) or {}
        character = {
            "id": entities.new_id("char_"),
            "name": r["name"], "age": r["age"], "occupation": r["occupation"],
            "quirk": quirk, "bio": bio or r["bio"],
            "place_id": home.get("id"), "place_name": home.get("name") or place,
            "founder_id": None, "history": [], "promoted_from": r["id"],
        }
        city_run.storage.add_character(character)
        city_run.storage.update_background_resident(r["id"], promoted_to=character["id"])
        _save_memories(r["name"], summary, events)
        created.append(character)
    return created


def _parse_bio(text: str):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    quirk = ""
    body = []
    for ln in lines:
        if ln.upper().startswith("QUIRK:"):
            quirk = ln.split(":", 1)[1].strip()
        else:
            body.append(ln)
    return " ".join(body).strip(), quirk


class _Resident:
    """Just the fields prompts.bio_upgrade reads."""

    def __init__(self, r: dict):
        self.name, self.age, self.occupation, self.bio = r["name"], r["age"], r["occupation"], r["bio"]
        self.work, self.haunt = r.get("work"), r.get("haunt")
