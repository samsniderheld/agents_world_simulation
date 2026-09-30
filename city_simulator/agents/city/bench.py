"""Headless CITY benchmark: how many LLM calls a tick makes and how long it
takes, at several population sizes.

    python3 -m agents.city.bench                         # stub server, 50/200/500/1000 agents
    python3 -m agents.city.bench --agents 200 1000 --ticks 8 --latency 0.2 --concurrency 64
    python3 -m agents.city.bench --real --profile rtx5090 --agents 200   # a real vLLM/Ollama

By default every request goes to agents/city/stub_server.py (no network,
nothing written): each request takes --latency seconds and --concurrency
requests run at once, like an ideal batching server. The "ideal" column is
what a tick would take if nothing but that server mattered: the sum over
the tick's batches of ceil(batch / concurrency) round trips, times the
latency. Waves run one after another (six dialogue turns are six round
trips), so a tick has a floor of about ten round trips; above that it grows
with requests / concurrency, not with agent count. A measured tick close to
the ideal means the Python side adds little.

Per population size it reports, averaged over the ticks:
  s/tick        wall time per tick (and the ideal, see above)
  calls/tick    chat requests per tick (embedding requests separately)
  hero, bg      calls per agent per tick, per tier ("bg" includes the
                start-of-day schedule; "bg steady" leaves those ticks out)
  waves         the slowest waves' share of the tick
Heroes default to 10% of the population (10-200); the city is synthetic
(40 places) unless --real, which uses the active city and its residents.
"""

import argparse
import random
import statistics
import time

import hardware

from . import config as ccfg
from . import prompts
from . import run as city_run
from .stub_server import StubServer

_PLACE_TYPES = ["Tavern/Bar", "Diner/Automat", "Nightclub/Jazz Club", "Shipyard/Dock/Warehouse", "Factory/Mill",
                "Bank/Counting House", "Grocery/Corner Store", "Hotel/Boarding House", "Apartment House",
                "Church/House of Worship", "Pool Hall", "Movie Palace", "Newspaper/Print Shop", "Hospital",
                "Government/Civic Building", "Restaurant", "Department Store", "Garage/Filling Station",
                "Park/Public Square", "Tenement/Residence"]


def synthetic_city(n_places: int, n_heroes: int, seed: int = 7) -> dict:
    rng = random.Random(seed)
    places = [{"id": f"place_{i}", "name": f"{_PLACE_TYPES[i % len(_PLACE_TYPES)].split('/')[0]} No. {i}",
               "status": "active", "place_type": _PLACE_TYPES[i % len(_PLACE_TYPES)]} for i in range(n_places)]
    characters = [{"id": f"char_{i}", "name": f"Hero {i:03d} {rng.choice(['Marino', 'Katz', 'Walsh', 'Greco'])}",
                   "age": rng.randint(25, 70), "occupation": rng.choice(["private eye", "singer", "cop", "fixer", "reporter"]),
                   "bio": "Someone with a past.", "place_name": places[i % n_places]["name"]} for i in range(n_heroes)]
    return {"summary": "A synthetic benchmark city.", "places": places, "characters": characters}


class _NullStorage:
    """Keeps the benchmark from reading or writing any city on disk."""

    def __init__(self, city):
        self.city = city
        self.background = []

    def get(self):
        return self.city

    def get_agent(self, _):
        return None

    def get_background(self):
        return list(self.background)

    def save_background(self, residents):
        self.background = list(residents)

    def save_city_run(self, summary):
        return None

    def append_agent_run(self, *a, **kw):
        return None


def bench_one(agents: int, args) -> dict:
    heroes = args.heroes if args.heroes is not None else max(10, min(200, agents // 10))
    heroes = min(heroes, agents)
    kwargs = dict(background_count=agents - heroes, ticks=args.ticks, tick_minutes=args.tick_minutes,
                  start_time="06:00", profile=args.profile, persist_hero_memories=False, seed=args.seed)
    server = None
    saved_storage = city_run.storage
    saved_profile = dict(hardware.CITY_PROFILES[args.profile])
    try:
        if args.real:
            city = city_run.storage.get()
            names = [c["name"] for c in (city or {}).get("characters", [])][:heroes]
            kwargs.update(hero_names=names or None)
        else:
            city = synthetic_city(args.places, heroes)
            server = StubServer(latency=args.latency, reply_fn=prompts.stub_reply, embed_dim=64, seed=args.seed)
            city_run.storage = _NullStorage(city)
            hardware.CITY_PROFILES[args.profile].update(
                max_concurrency=args.concurrency, population_cap=max(agents, saved_profile["population_cap"]),
                hero_cap=max(heroes, saved_profile["hero_cap"]),
                llm_schedule_cap=max(agents, saved_profile.get("llm_schedule_cap") or 0))
            kwargs.update(transport=server.transport(), city=city, hero_model="stub-hero",
                          background_model="stub-background")
        started = time.monotonic()
        world = city_run.run(**kwargs)
        wall = time.monotonic() - started
    finally:
        city_run.storage = saved_storage
        hardware.CITY_PROFILES[args.profile].clear()
        hardware.CITY_PROFILES[args.profile].update(saved_profile)

    ticks = world.metrics_history
    n_hero = max(1, statistics.mean(m["heroes"] for m in ticks))
    n_bg = max(1, statistics.mean(m["background"] for m in ticks))
    chat = [m["requests"] - m["calls_by_kind"].get("embed", 0) for m in ticks]
    embed = [m["calls_by_kind"].get("embed", 0) for m in ticks]
    day_starts = {i for i, m in enumerate(ticks) if m["calls_by_kind"].get("schedule")}
    steady = [m for i, m in enumerate(ticks) if i not in day_starts] or ticks
    waves = {}
    for m in ticks:
        for w, s in m["waves"].items():
            waves[w] = waves.get(w, 0) + s
    total = sum(waves.values()) or 1
    top = sorted(waves.items(), key=lambda kv: -kv[1])[:3]
    return {
        "agents": agents, "heroes": heroes, "background": agents - heroes, "ticks": len(ticks), "wall": wall,
        "s_per_tick": statistics.mean(m["seconds"] for m in ticks),
        "ideal_per_tick": (sum(m["rounds"] for m in ticks) * args.latency / len(ticks)) if not args.real else None,
        "calls_per_tick": statistics.mean(chat), "embeds_per_tick": statistics.mean(embed),
        "hero_calls": statistics.mean(m["calls_by_tier"].get("hero", 0) for m in ticks) / n_hero,
        "bg_calls": statistics.mean(m["calls_by_tier"].get("background", 0) for m in ticks) / n_bg,
        "bg_steady": statistics.mean(m["calls_by_tier"].get("background", 0) for m in steady) / n_bg,
        "failures": sum(m["failures"] for m in ticks),
        "waves": ", ".join(f"{w} {100 * s / total:.0f}%" for w, s in top),
        "peak_in_flight": server.peak if server else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--agents", type=int, nargs="+", default=[50, 200, 500, 1000])
    parser.add_argument("--heroes", type=int, default=None, help="default: 10%% of agents, 10-200")
    parser.add_argument("--ticks", type=int, default=16)
    parser.add_argument("--tick-minutes", type=int, default=90, help="default 90: 16 ticks = one sim-day")
    parser.add_argument("--places", type=int, default=40)
    parser.add_argument("--latency", type=float, default=0.05, help="stub: seconds per request")
    parser.add_argument("--concurrency", type=int, default=64, help="stub: max requests in flight")
    parser.add_argument("--profile", default="rtx5090", choices=sorted(hardware.CITY_PROFILES))
    parser.add_argument("--seed", type=int, default=ccfg.DEFAULT_SEED)
    parser.add_argument("--real", action="store_true", help="use the profile's real backends and the active city")
    args = parser.parse_args(argv)

    rows = []
    for n in args.agents:
        print(f"running {n} agents...", flush=True)
        rows.append(bench_one(n, args))

    mode = "real backends" if args.real else f"stub server: {args.latency}s/request, {args.concurrency} in flight"
    print(f"\nCITY benchmark -- {mode}, {args.ticks} ticks of {args.tick_minutes} min, profile {args.profile}\n")
    head = f"{'agents':>6} {'heroes':>6} {'bg':>5} {'s/tick':>7} {'ideal':>6} {'calls/tick':>10} {'embeds':>6} " \
           f"{'hero':>6} {'bg':>6} {'bg steady':>9} {'fail':>4}  slowest waves"
    print(head)
    print("-" * len(head))
    for r in rows:
        ideal = f"{r['ideal_per_tick']:.2f}" if r["ideal_per_tick"] is not None else "-"
        print(f"{r['agents']:>6} {r['heroes']:>6} {r['background']:>5} {r['s_per_tick']:>7.2f} {ideal:>6} "
              f"{r['calls_per_tick']:>10.1f} {r['embeds_per_tick']:>6.1f} {r['hero_calls']:>6.2f} {r['bg_calls']:>6.3f} "
              f"{r['bg_steady']:>9.3f} {r['failures']:>4}  {r['waves']}")
    print("\nhero / bg / bg steady = LLM calls per agent per tick for that tier; target: bg < 0.2.")
    return rows


if __name__ == "__main__":
    main()
