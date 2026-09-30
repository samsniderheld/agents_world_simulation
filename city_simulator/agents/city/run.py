"""Entry point for a CITY run: agents/jobs.py calls run() on the job thread.
Blocking; everything it does is streamed through agents/city/recorder.py.

run() resolves the hardware profile and each tier's backend, builds the
heroes (the wired-in characters, or every generated resident of the active
city, hydrated with their memories from earlier runs of either mode) and
the background population, then runs one asyncio loop with one Gateway for
the whole run.
"""

import asyncio
import datetime

import hardware
from citystate import store as citystate

from .. import config as scene_config
from .. import display
from ..gateway import Gateway, backends_for_profile
from . import config as ccfg
from . import population as pop
from . import recorder
from .tiers import BackgroundAgent, CityHero, CityMemoryStream

_DEFAULT_DATE = datetime.datetime(2026, 8, 24)   # the same calendar day SCENE runs use


def build_heroes(city: dict, hero_names: list = None, cap: int = 200, hydrate: bool = True) -> list:
    """CityHero per chosen character (all of them if none are named),
    placed at their own grounding place, remembering earlier runs."""
    characters = city.get("characters", [])
    if hero_names:
        wanted = set(hero_names)
        characters = [c for c in characters if c["name"] in wanted]
    heroes = []
    for c in characters[:cap]:
        traits = (c.get("occupation") or "").strip()
        quirk = (c.get("quirk") or "").strip()
        if quirk:
            traits = f"{traits}; {quirk}" if traits else quirk
        place = c.get("place_name") or "the city"
        hero = CityHero(name=c["name"], age=c.get("age", 40), traits=traits or "a longtime local",
                        currently=c.get("bio", ""), location=place, character_id=c.get("id"), home=place)
        if hydrate and c.get("id"):
            record = citystate.get_agent(c["id"])
            if record and record.get("runs"):
                hero.memory = CityMemoryStream.from_persisted(record)
        heroes.append(hero)
    return heroes


def build_background(city: dict, count: int, seed: int, taken_names: set) -> list:
    """`count` background residents: the city's saved ones first, topped
    up deterministically from the seed (see population.generate)."""
    if count <= 0:
        return []
    saved = citystate_background()
    if len(saved) < count:
        saved = pop.generate(city, count, seed, taken_names=taken_names, start=len(saved), existing=saved)
        save_background(saved)
    active = {p["name"] for p in city.get("places", []) if p.get("status") == "active"}
    residents = []
    for record in saved[:count]:
        if record["name"] in taken_names:
            continue
        record = dict(record)
        for key in ("work", "haunt", "home"):      # a place that has since closed
            if record.get(key) and record[key] not in active:
                record[key] = None
        residents.append(BackgroundAgent(record))
    return residents


# Storage hooks for the background population (see citystate); kept as
# module functions so tests can swap them out.
def citystate_background() -> list:
    getter = getattr(citystate, "get_background", None)
    return list(getter() or []) if getter else []


def save_background(residents: list):
    saver = getattr(citystate, "save_background", None)
    if saver:
        saver(residents)


async def _preflight(gw: Gateway, backends: dict) -> list:
    """Make sure every tier's server answers and has its model; a tier
    whose model is missing falls back to the hero model (or, on Ollama, to
    SCENE's chat model). Returns warnings for the run log."""
    warnings = []
    listed = {}
    for tier in ("hero", "background"):
        b = backends[tier]
        key = (b.provider, b.base_url)
        if key not in listed:
            try:
                listed[key] = await gw.available_models(b)
            except Exception as e:
                raise RuntimeError(f"Could not reach the {tier} tier's {b.provider} server at {b.base_url}: {e}")
        models = [m for m in listed[key] if "embed" not in m]
        if b.provider == "claude" or _has_model(models, b.model):
            continue
        fallback = backends["hero"].model if tier == "background" and _has_model(models, backends["hero"].model) \
            else next((m for m in (scene_config.CHAT_MODEL,) if _has_model(models, m)), models[0] if models else None)
        if not fallback:
            raise RuntimeError(f"The {tier} model {b.model!r} isn't available at {b.base_url}, and nothing else is.")
        warnings.append(f"{tier} model {b.model!r} isn't available; using {fallback!r} instead"
                        + (f" (pull it with `ollama pull {b.model}`)" if b.provider == "ollama" else ""))
        b.model = fallback
    try:
        await gw.embed_many(["ping"])
    except Exception as e:
        raise RuntimeError(f"Embeddings need Ollama with {ccfg.EMBED_MODEL} at {gw.embed_base_url}: {e}")
    return warnings


def _has_model(models: list, name: str) -> bool:
    if not name:
        return False
    return name in models or name.split(":")[0] in {m.split(":")[0] for m in models} and ":" not in name


def run(stop_flag=None, hero_names=None, background_count=0, profile="auto", hero_provider=None, hero_model=None,
        background_provider=None, background_model=None, ticks=ccfg.DEFAULT_TICKS, tick_minutes=None,
        start_time=None, directive=None, convene_at=None, persist_hero_memories=True, seed=None,
        pause_flag=None, transport=None, city=None, llm_schedules=None, on_world=None):
    """Blocking. `transport` (an httpx transport) and `city` are for tests
    and the benchmark; `on_world` receives the CityWorld once built (the
    routes use it to queue UI promotions)."""
    city = city if city is not None else citystate.get()
    if not city:
        raise RuntimeError("no active city -- generate one first")
    prof = hardware.city_profile(profile)
    backends = backends_for_profile(prof, hero_provider, hero_model, background_provider, background_model)
    seed = ccfg.DEFAULT_SEED if seed is None else seed
    tick_minutes = tick_minutes or scene_config.TICK_MINUTES
    hour, minute = (int(x) for x in (start_time or "06:00").split(":"))
    start = _DEFAULT_DATE.replace(hour=hour, minute=minute)

    heroes = build_heroes(city, hero_names, cap=prof["hero_cap"], hydrate=transport is None)
    if convene_at:
        for h in heroes:
            h.location = convene_at
            h.anchored = True
    room = max(0, prof["population_cap"] - len(heroes))
    count = min(background_count or 0, room)
    background = build_background(city, count, seed, {h.name for h in heroes}) if count else []

    return asyncio.run(_main(
        city, prof, backends, heroes, background, start, tick_minutes, ticks, directive, convene_at, seed,
        stop_flag, pause_flag, transport, persist_hero_memories,
        ccfg.BACKGROUND_LLM_SCHEDULES if llm_schedules is None else llm_schedules,
        clipped=(background_count or 0) - count, on_world=on_world))


async def _main(city, prof, backends, heroes, background, start, tick_minutes, ticks, directive, convene_at, seed,
                stop_flag, pause_flag, transport, persist, llm_schedules, clipped=0, on_world=None):
    from .world import CityWorld

    async with Gateway(backends, transport=transport) as gw:
        warnings = await _preflight(gw, backends)
        colors = display.agent_hex_colors([h.name for h in heroes])
        recorder.start(
            heroes=[{"name": h.name, "color": colors[h.name], "age": h.age, "traits": h.traits,
                     "location": h.location, "tier": "hero"} for h in heroes],
            meta={
                "profile": prof["name"],
                "provider": backends["hero"].provider,
                "chat_model": backends["hero"].model,
                "background_provider": backends["background"].provider,
                "background_model": backends["background"].model,
                "embed_model": ccfg.EMBED_MODEL,
                "context_tokens": prof["context_tokens"],
                "max_concurrency": backends["hero"].max_concurrency,
                "ticks": ticks, "tick_minutes": tick_minutes, "start_time": start.strftime("%H:%M"),
                "directive": directive, "convene_at": convene_at, "seed": seed,
                "persist_hero_memories": persist, "llm_schedules": llm_schedules,
            },
            population={"heroes": len(heroes), "background": len(background)},
        )
        for w in warnings:
            recorder.log("status", 0, tier=None, text=w)
        if clipped > 0:
            recorder.log("status", 0, tier=None,
                         text=f"{clipped} background residents left out: the {prof['name']} profile caps a run at "
                              f"{prof['population_cap']} agents")
        recorder.log("status", 0, tier=None,
                     text=f"{len(heroes)} heroes ({backends['hero'].label()}), {len(background)} background "
                          f"residents ({backends['background'].label()}), {ticks} ticks of {tick_minutes} min")
        world = CityWorld(gw, heroes, background, city, start=start, tick_minutes=tick_minutes, directive=directive,
                          seed=seed, stop_flag=stop_flag, pause_flag=pause_flag, llm_schedules=llm_schedules,
                          hero_cap=prof["hero_cap"], llm_schedule_cap=prof.get("llm_schedule_cap"))
        if on_world:
            on_world(world)
        await world.run(ticks)
        recorder.log("status", world.tick, tier=None, text=f"finished after {world.tick} ticks")
        return world
