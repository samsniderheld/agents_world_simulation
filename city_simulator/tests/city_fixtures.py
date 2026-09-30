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


class FakeStorage:
    """Stands in for citystate.store in CITY runs (agents/city/run.py's
    `storage`): an in-memory city, background list, run summaries,
    appended runs and characters. Nothing touches disk."""

    def __init__(self, city=None):
        self.city = city or fake_city()
        self.background = []
        self.city_runs = []
        self.appended = []
        self.records = {}
        self.added = []

    def get(self):
        return self.city

    def get_agent(self, agent_id):
        return self.records.get(agent_id)

    def get_background(self):
        return list(self.background)

    def save_background(self, residents):
        self.background = list(residents)

    def update_background_resident(self, resident_id, **fields):
        for r in self.background:
            if r["id"] == resident_id:
                r.update(fields)
                return True
        return False

    def save_city_run(self, summary):
        self.city_runs.append(summary)
        return "run.json"

    def get_city_run(self, started_at=None):
        runs = [s for s in self.city_runs if not started_at or s["started_at"] == started_at]
        return runs[-1] if runs else None

    def append_agent_run(self, run_record):
        self.appended.append(run_record)

    def add_character(self, character):
        self.city["characters"].append(character)
        self.added.append(character)
        return character


@contextlib.contextmanager
def fake_storage(storage: FakeStorage = None):
    storage = storage or FakeStorage()
    saved = city_run.storage
    city_run.storage = storage
    try:
        yield storage
    finally:
        city_run.storage = saved


no_background_storage = fake_storage


def run_city(server: StubServer = None, **kw):
    server = server or StubServer(reply_fn=prompts.stub_reply)
    params = dict(background_count=40, ticks=3, profile="mac", transport=server.transport(), city=fake_city(),
                  tick_minutes=60, start_time="17:00", hero_model="stub-hero", background_model="stub-background")
    params.update(kw)
    storage = params.pop("storage", None) or FakeStorage(params["city"])
    with fake_storage(storage):
        world = city_run.run(**params)
    world.storage = storage
    return world, server


def stub_gateway(server: StubServer, limit: int = 4):
    backends = {t: Backend("ollama", f"stub-{t}", "http://stub:11434", max_concurrency=limit)
                for t in ("hero", "background")}
    return Gateway(backends, embed_base_url="http://stub:11434", transport=server.transport(), backoff_base=0.001)


START = datetime.datetime(2026, 8, 24, 17, 0)


def arun(coro):
    return asyncio.run(coro)
