"""A small fake city and helpers for running CITY mode against the stub
server without touching the real citystate."""

import asyncio
import contextlib
import datetime

from agents.city import prompts
from agents.city import run as city_run
from agents.city.stub_server import StubServer
from agents.gateway import Backend, Gateway

PLACES = [("Ozzy's Bar", "Tavern/Bar"), ("The Blue Note", "Nightclub/Jazz Club"),
          ("Pier 9", "Shipyard/Dock/Warehouse"), ("Mott Street Diner", "Diner/Automat"),
          ("St. Agnes", "Church/House of Worship"), ("Carlton Apartments", "Apartment House")]
HEROES = [("Lou Marino", "private eye", "Ozzy's Bar"), ("Vera Katz", "singer", "The Blue Note"),
          ("Sal Greco", "mob boss", "Ozzy's Bar"), ("Tom Walsh", "cop", "Pier 9")]


def fake_city() -> dict:
    return {
        "summary": "A harbor city of bars and secrets.",
        "places": [{"id": f"place_{i}", "name": n, "status": "active", "place_type": t, "architecture": f"{n} facade"}
                   for i, (n, t) in enumerate(PLACES)],
        "characters": [{"id": f"char_{i}", "name": n, "age": 40 + i, "occupation": o, "bio": f"{n} is trouble.",
                        "place_name": p, "place_id": f"place_{[x for x, _ in PLACES].index(p)}"}
                       for i, (n, o, p) in enumerate(HEROES)],
    }


@contextlib.contextmanager
def no_background_storage():
    saved = (city_run.citystate_background, city_run.save_background)
    store = []
    city_run.citystate_background = lambda: list(store)
    city_run.save_background = lambda r: store.__setitem__(slice(None), r)
    try:
        yield store
    finally:
        city_run.citystate_background, city_run.save_background = saved


def run_city(server: StubServer = None, **kw):
    server = server or StubServer(reply_fn=prompts.stub_reply)
    params = dict(background_count=40, ticks=3, profile="mac", transport=server.transport(), city=fake_city(),
                  tick_minutes=60, start_time="17:00", hero_model="stub-hero", background_model="stub-background")
    params.update(kw)
    with no_background_storage():
        world = city_run.run(**params)
    return world, server


def stub_gateway(server: StubServer, limit: int = 4):
    backends = {t: Backend("ollama", f"stub-{t}", "http://stub:11434", max_concurrency=limit)
                for t in ("hero", "background")}
    return Gateway(backends, embed_base_url="http://stub:11434", transport=server.transport(), backoff_base=0.001)


START = datetime.datetime(2026, 8, 24, 17, 0)


def arun(coro):
    return asyncio.run(coro)
