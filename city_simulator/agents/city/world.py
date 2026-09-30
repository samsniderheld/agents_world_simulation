"""The CITY tick loop. Each tick is a sequence of waves; each wave collects
every request it needs, sends them all at once (gateway.generate_many /
embed_many), then applies the results. All state is mutated on the one
event-loop task between waves, so nothing needs a lock.

    tick
    ├─ PLAN        heroes without a plan: a plan for the rest of the run
    │              background agents at the start of each sim-day: one JSON
    │              schedule (or an occupation template)
    ├─ DECOMPOSE   heroes entering a new plan item: one action per tick, and
    │              where to be; background agents follow their schedule
    ├─ ENCOUNTERS  group everyone by place; per place, up to N encounters,
    │              no agent in two (heroes first). Background-background
    │              encounters resolve in Python, no LLM
    ├─ REACT       each encounter with a hero: TALK / REACT / CONTINUE
    ├─ DIALOGUE    every conversation advances one line per batch, in
    │              lockstep, up to 6 lines or [END]
    ├─ MEMORY      every hero memory added this tick: one importance call
    │              per hero, one embed_many for all of them
    ├─ REFLECT     heroes over the threshold: focal points, then insights
    └─ PROMOTE     background agents who've dealt with heroes enough (or
                   were picked in the UI) become heroes
"""

import asyncio
import collections
import contextlib
import datetime
import hashlib
import random
import time

from .. import display
from ..config import REFLECTION_IMPORTANCE_THRESHOLD, REFLECTION_INSIGHTS_PER_FOCAL_POINT, \
    REFLECTION_LOOKBACK, REFLECTION_NUM_FOCAL_POINTS
from ..gateway import LLMRequest
from ..planning import MAX_PLAN_ITEMS, _duration, _substep_length
from ..world import clock_label
from . import config as ccfg
from . import population as pop
from . import prompts
from . import recorder
from .tiers import ELSEWHERE, HOME, BackgroundAgent, CityHero, clock_minutes, validate_schedule

_TOPICS = ["the weather", "the ball game", "a rumor about the precinct", "rent going up", "the numbers",
           "somebody's cousin", "the new place on the corner", "work", "an old debt", "the neighborhood"]


class CityWorld:
    def __init__(self, gateway, heroes: list, background: list, city: dict, *, start: datetime.datetime,
                 tick_minutes: int, directive: str = None, seed: int = ccfg.DEFAULT_SEED,
                 stop_flag=None, pause_flag=None, llm_schedules: bool = ccfg.BACKGROUND_LLM_SCHEDULES,
                 hero_cap: int = 200, promote_after: int = ccfg.PROMOTE_AFTER_HERO_INTERACTIONS,
                 max_encounters_per_place: int = ccfg.MAX_ENCOUNTERS_PER_PLACE, llm_schedule_cap: int = None):
        self.gw = gateway
        self.heroes = list(heroes)
        self.background = list(background)
        self.city = city
        self.start = start
        self.tick_minutes = tick_minutes
        self.directive = directive
        self.seed = seed
        self.stop_flag = stop_flag
        self.pause_flag = pause_flag
        self.llm_schedules = llm_schedules
        self.hero_cap = hero_cap
        self.promote_after = promote_after
        self.max_encounters = max_encounters_per_place
        self.llm_schedule_cap = llm_schedule_cap
        self.tick = 0
        self.total_ticks = 0
        self.until = None
        self.prefix = prompts.city_prefix(city)
        self.places = sorted({p["name"] for p in (city or {}).get("places", [])
                              if p.get("status") == "active" and p.get("name")})
        self.schedule_places = pop.schedule_places(city)
        self.colors = display.agent_hex_colors([h.name for h in self.heroes])
        self.promotion_requests = collections.deque()
        self.metrics_history = []
        self.finished = False
        self._by_place = {}
        self._wave_metrics = {}

    # --- helpers ------------------------------------------------------------------------

    @property
    def now(self) -> datetime.datetime:
        return self.start + datetime.timedelta(minutes=self.tick_minutes * self.tick)

    def clock(self) -> str:
        return clock_label(self.start, self.now, self.tick_minutes)

    def _seed(self, agent: str, kind: str) -> int:
        return int(hashlib.md5(f"{self.seed}:{self.tick}:{agent}:{kind}".encode()).hexdigest()[:8], 16) & 0x7FFFFFFF

    def _request(self, agent, specifics: str, kind: str, schema: dict = None, max_tokens: int = 200,
                 temperature: float = 0.7) -> LLMRequest:
        hero = agent.tier == "hero"
        identity = prompts.hero_identity(agent) if hero else prompts.background_identity(agent)
        return LLMRequest(agent=agent.name, tier=agent.tier,
                          prompt_parts=[self.prefix, prompts.HERO_TIER if hero else prompts.BACKGROUND_TIER,
                                        identity, specifics],
                          schema=schema, max_tokens=max_tokens, temperature=temperature,
                          seed=self._seed(agent.name, kind), kind=kind)

    @contextlib.asynccontextmanager
    async def _wave(self, name: str):
        self.gw.take_stats()
        t0 = time.monotonic()
        yield
        stats = self.gw.take_stats()
        self._wave_metrics[name] = {
            "seconds": round(time.monotonic() - t0, 3), "requests": stats["requests"],
            "tokens_in": stats["tokens_in"], "tokens_out": stats["tokens_out"], "retries": stats["retries"],
            "failures": stats["failures"], "repairs": stats["repairs"], "backpressure": stats["backpressure"],
            "by_tier": stats["by_tier"], "by_kind": stats["by_kind"],
        }

    def _cast(self, hero, extra: list = ()) -> list:
        """The people a hero's prompt may name: whoever else is here
        (heroes first), who they're dealing with, and who they know best."""
        here = [a for a in self._by_place.get(hero.location, []) if a is not hero]
        here.sort(key=lambda a: a.tier != "hero")
        known = [n for n, _ in hero.acquaintances.most_common(5)]
        return list(dict.fromkeys(list(extra) + [a.name for a in here[:8]] + known))

    def _hero_places(self, hero) -> list:
        """Up to 12 places offered to a hero deciding where to be: home,
        here, where other heroes are, then a stable per-hero sample."""
        if hero.anchored or len(self.places) < 2:
            return []
        rng = random.Random(f"{self.seed}:{hero.name}:{self.tick}")
        picks = [hero.home, hero.location] + [h.location for h in self.heroes if h is not hero]
        sample = [p for p in self.places]
        rng.shuffle(sample)
        return [p for p in dict.fromkeys(picks + sample) if p in self.places][:12]

    def _log(self, kind: str, agent, **fields):
        tier = agent.tier if agent is not None and hasattr(agent, "tier") else None
        name = agent.name if agent is not None and hasattr(agent, "name") else agent
        recorder.log(kind, self.tick, agent=name, tier=tier, **fields)

    # --- the loop -------------------------------------------------------------------------

    async def run(self, ticks: int):
        self.total_ticks = ticks
        end = self.start + datetime.timedelta(minutes=self.tick_minutes * ticks)
        self.until = clock_label(self.start, end, self.tick_minutes)
        for _ in range(ticks):
            while self.pause_flag is not None and self.pause_flag.is_set() and not self._stopped():
                await asyncio.sleep(0.2)
            if self._stopped():
                break
            await self.step()

    def _stopped(self) -> bool:
        return bool(self.stop_flag is not None and self.stop_flag.is_set())

    async def step(self):
        tick_started = time.monotonic()
        self._wave_metrics = {}
        self.gw.take_stats()
        async with self._wave("plan"):
            await self._plan_wave()
        async with self._wave("decompose"):
            await self._decompose_wave()
        async with self._wave("encounters"):
            hero_encounters = self._encounters()
        async with self._wave("react"):
            conversations = await self._react_wave(hero_encounters)
        async with self._wave("dialogue"):
            await self._dialogue_wave(conversations)
        async with self._wave("memory"):
            await self._memory_wave()
        async with self._wave("reflect"):
            await self._reflect_wave()
        async with self._wave("promote"):
            await self._promote_wave()
        self._record_summary(len(hero_encounters), len(conversations))
        self._record_metrics(time.monotonic() - tick_started, len(hero_encounters), len(conversations))
        self.tick += 1

    # --- PLAN ----------------------------------------------------------------------------------

    async def _plan_wave(self):
        heroes = [h for h in self.heroes if not h.plan]
        day = (self.now.date() - self.start.date()).days
        background = [b for b in self.background if b.schedule_day != day]
        remaining = max(1, self.total_ticks - self.tick)
        n_items = min(remaining, MAX_PLAN_ITEMS)
        horizon = remaining * self.tick_minutes

        queries = [f"{h.name}'s past plans, goals, and what actually happened" for h in heroes]
        vectors = await self.gw.embed_many(queries) if any(h.memory.nodes for h in heroes) else [[] for _ in heroes]
        requests = []
        for h, q in zip(heroes, vectors):
            memories = [m.description for m in h.memory.retrieve_embedded(q, self.tick, k=8)]
            requests.append(self._request(
                h, prompts.hero_plan(h, memories, self._cast(h), self.directive, _duration(horizon),
                                     _duration(horizon / n_items), n_items, self.clock(), self.until),
                "plan", prompts.plan_schema(n_items), ccfg.TOKENS_PLAN))
        llm_background = self._schedule_picks(background) if self.llm_schedules else []
        day_label = (self.now.strftime("%A") + (f" (day {day + 1})" if day else ""))
        schema = prompts.schedule_schema(self.schedule_places)
        for b in llm_background:
            directive = prompts.directive_for_background(self.directive, b)
            requests.append(self._request(b, prompts.background_schedule(b, self.schedule_places, day_label, directive),
                                          "schedule", schema, ccfg.TOKENS_SCHEDULE, 0.8))
        results = await self.gw.generate_many(requests)

        for h, r in zip(heroes, results[:len(heroes)]):
            items = [str(x).strip() for x in (r.data or {}).get("items", []) if str(x).strip()][:n_items] if r.ok else []
            if not items:
                items = [f"going about the day as usual: {h.currently[:80]}"]
                self._log("status", h, text=f"plan call failed ({r.error}); using a default plan")
            h.plan = items
            n = len(items)
            h.plan_bounds = [(self.tick + k * remaining // n, self.tick + (k + 1) * remaining // n) for k in range(n)]
            h.current_item = -1
            self._log("plan", h, items=items)
            h.memory.queue_add(f"{h.name}'s plan for the next {_duration(horizon)}: {'; '.join(items)}", "plan", self.tick)

        allowed = set(self.schedule_places)
        sources = collections.Counter()
        llm_results = dict(zip((b.id for b in llm_background), results[len(heroes):]))
        for b in background:
            r = llm_results.get(b.id)
            blocks = validate_schedule((r.data or {}).get("schedule"), allowed) if r is not None and r.ok else []
            if blocks:
                b.schedule, b.schedule_source = blocks, "llm"
            else:   # not asked, or the call failed / came back unusable
                b.schedule = pop.template_schedule(b, random.Random(f"{self.seed}:{b.id}:{day}"))
                b.schedule_source = "template"
            b.schedule_day = day
            sources[b.schedule_source] += 1
        if background:
            recorder.log("schedules", self.tick, tier="background",
                         text=f"{sources.get('llm', 0)} schedules from the model, {sources.get('template', 0)} from templates",
                         llm=sources.get("llm", 0), template=sources.get("template", 0))

    def _schedule_picks(self, background: list) -> list:
        """Who gets a model-written schedule today, within the profile's
        llm_schedule_cap: residents whose work, haunt or home is where a
        hero lives or is come first (they're the ones heroes will meet);
        the rest keep occupation templates."""
        if self.llm_schedule_cap is None or len(background) <= self.llm_schedule_cap:
            return list(background)
        hot = {h.home for h in self.heroes} | {h.location for h in self.heroes}
        ranked = sorted(background, key=lambda b: (not ({b.work, b.haunt, b.home} & hot), b.id))
        return ranked[:self.llm_schedule_cap]

    # --- DECOMPOSE -------------------------------------------------------------------------------

    async def _decompose_wave(self):
        todo = []
        for h in self.heroes:
            item = next((k for k, (s, e) in enumerate(h.plan_bounds) if s <= self.tick < e), len(h.plan_bounds) - 1)
            if item != h.current_item:
                start, end = h.plan_bounds[item]
                todo.append((h, item, max(1, end - start), self._hero_places(h)))
        requests = [self._request(h, prompts.hero_decompose(h, h.plan[item], n, _substep_length(self.tick_minutes),
                                                            self._cast(h), self.directive, self.clock(), places),
                                  "decompose", prompts.decompose_schema(n, places), ccfg.TOKENS_DECOMPOSE)
                    for h, item, n, places in todo]
        results = await self.gw.generate_many(requests)
        for (h, item, n, places), r in zip(todo, results):
            data = r.data if r.ok else {}
            actions = [str(a).strip() for a in (data or {}).get("actions", []) if str(a).strip()][:n] or [h.plan[item]]
            h.current_item = item
            h.substeps = actions
            self._log("decompose", h, broad_step=h.plan[item], items=actions)
            h.memory.queue_add(f"{h.name} broke '{h.plan[item]}' into: {'; '.join(actions)}", "plan", self.tick)
            where = (data or {}).get("where")
            if where and where != "STAY" and where in self.places and where != h.location:
                self._move_hero(h, where)

        for h in self.heroes:
            start = h.plan_bounds[h.current_item][0]
            h.current_action = h.substeps[min(max(0, self.tick - start), len(h.substeps) - 1)]
            self._log("action", h, text=h.current_action, location=h.location, time=self.clock())
            h.memory.queue_add(f"{h.name} is {h.current_action}", "observation", self.tick)

        minute = clock_minutes(self.now)
        moved = 0
        for b in self.background:
            block = b.block_at(minute) or (b.schedule[-1] if b.schedule else None)
            if block is None:
                continue
            if b.location is not None and block.place != b.location:
                moved += 1
                self._log("move", b, from_location=b.location_label(), to_location=_label(block.place, b))
            b.location = block.place
            b.current_action = block.activity
        if moved:
            recorder.log("moves", self.tick, tier="background", text=f"{moved} background residents moved", count=moved)

        self._index_places()
        recorder.set_positions(self.tick, {**{h.name: h.location for h in self.heroes},
                                           **{b.name: b.location_label() for b in self.background}})

    def _move_hero(self, h, destination: str):
        self._log("move", h, from_location=h.location, to_location=destination)
        h.memory.queue_add(f"{h.name} moved from {h.location} to {destination}.", "observation", self.tick)
        h.location = destination
        recorder.update_hero_location(h.name, destination)

    def _index_places(self):
        by_place = collections.defaultdict(list)
        for h in self.heroes:
            by_place[h.location].append(h)
        for b in self.background:
            by_place[b.map_location()].append(b)
        self._by_place = by_place

    # --- ENCOUNTERS ------------------------------------------------------------------------------

    def _encounters(self) -> list:
        """Per place, up to max_encounters pairs, each agent in at most one:
        hero-hero first, then hero-background, then background-background.
        Background-background encounters are settled right here."""
        hero_encounters = []
        topics = random.Random(f"{self.seed}:{self.tick}:topics")
        for place in sorted(self._by_place):
            people = self._by_place[place]
            if place.startswith("~") or len(people) < 2:
                continue
            rng = random.Random(f"{self.seed}:{self.tick}:{place}")
            heroes = [p for p in people if p.tier == "hero"]
            bgs = [p for p in people if p.tier != "hero"]
            rng.shuffle(heroes)
            rng.shuffle(bgs)
            pairs = []
            while len(heroes) >= 2 and len(pairs) < self.max_encounters:
                pairs.append((heroes.pop(), heroes.pop()))
            while heroes and bgs and len(pairs) < self.max_encounters:
                pairs.append((heroes.pop(), bgs.pop()))
            while len(bgs) >= 2 and len(pairs) < self.max_encounters:
                pairs.append((bgs.pop(), bgs.pop()))
            for a, b in pairs:
                a.acquaintances[b.name] += 1
                b.acquaintances[a.name] += 1
                label = _label(place, a)
                if a.tier == "hero":
                    hero_encounters.append((a, b, label))
                    self._log("encounter", a, text=f"ran into {b.name}", other=b.name, place=label)
                else:
                    topic = topics.choice(_TOPICS)
                    for x, y in ((a, b), (b, a)):
                        x.memory.add(self.tick, "encounter", f"Traded a few words with {y.name} at {label} about {topic}.")
                    self._log("encounter", a, text=f"traded a few words with {b.name} about {topic}",
                              other=b.name, place=label)
        return hero_encounters

    # --- REACT -----------------------------------------------------------------------------------

    async def _react_wave(self, encounters: list) -> list:
        if not encounters:
            return []
        observations = [f"{other.name} is nearby, currently: {other.current_action}." for _, other, _ in encounters]
        vectors = await self.gw.embed_many(observations)
        requests = []
        for (h, other, place), q in zip(encounters, vectors):
            memories = [m.description for m in h.memory.retrieve_embedded(q, self.tick, k=6)]
            requests.append(self._request(h, prompts.hero_react(h, other.name, other.current_action, memories,
                                                                self._cast(h, [other.name]), self.directive),
                                          "react", None, ccfg.TOKENS_REACT, 0.6))
        results = await self.gw.generate_many(requests)
        conversations = []
        for (h, other, place), observation, r in zip(encounters, observations, results):
            self._log("observe", h, text=observation)
            h.memory.queue_add(f"Observed: {observation}", "observation", self.tick)
            tag, text = prompts.parse_react(r.text) if r.ok else ("continue", "")
            if tag == "talk":
                h.current_action = f"talking with {other.name} about {text}"
                h.memory.queue_add(f"{h.name} decided to: {h.current_action}", "observation", self.tick)
                self._log("react", h, text=h.current_action)
                conversations.append(_Conversation(h, other, place, text))
            elif tag == "react":
                h.current_action = text
                h.memory.queue_add(f"{h.name} decided to: {text}", "observation", self.tick)
                self._log("react", h, text=text)
            else:
                self._log("continue", h)
        return conversations

    # --- DIALOGUE ----------------------------------------------------------------------------------

    async def _dialogue_wave(self, conversations: list):
        if not conversations:
            return
        hero_queries = [(c, s, o) for c in conversations for s, o in ((c.a, c.b), (c.b, c.a)) if s.tier == "hero"]
        vectors = await self.gw.embed_many([f"{o.name}: a conversation with {o.name}" for _, _, o in hero_queries])
        for (c, s, o), q in zip(hero_queries, vectors):
            c.memories[s.name] = [m.description for m in s.memory.retrieve_embedded(q, self.tick, k=5)]
        for c in conversations:
            for s, o in ((c.a, c.b), (c.b, c.a)):
                if s.tier != "hero":
                    c.memories[s.name] = [e.text for e in s.memory.retrieve(o.name, k=4)]

        for turn in range(ccfg.MAX_DIALOGUE_TURNS):
            active = [c for c in conversations if not c.ended]
            if not active:
                break
            requests = []
            for c in active:
                speaker, listener = (c.a, c.b) if turn % 2 == 0 else (c.b, c.a)
                is_hero = speaker.tier == "hero"
                directive = self.directive if is_hero else prompts.directive_for_background(self.directive, speaker)
                cast = self._cast(speaker, [listener.name]) if is_hero else [listener.name]
                requests.append(self._request(
                    speaker, prompts.dialogue_line(is_hero, speaker, listener.name, c.place, c.topic,
                                                   c.memories.get(speaker.name, []), c.lines, cast, directive,
                                                   turn, ccfg.MAX_DIALOGUE_TURNS),
                    "dialogue" if is_hero else "dialogue_bg", None, ccfg.TOKENS_LINE, 0.8))
            results = await self.gw.generate_many(requests)
            for c, r in zip(active, results):
                speaker, listener = (c.a, c.b) if turn % 2 == 0 else (c.b, c.a)
                line = prompts.parse_line(r.text, speaker.name) if r.ok else None
                if line is None:
                    c.ended = True
                    continue
                c.lines.append(f"{speaker.name}: {line}")
                keep = tuple(x.name for x in (listener,) if x.tier == "hero" and speaker.tier != "hero")
                recorder.log("dialogue", self.tick, agent=speaker.name, tier="hero", keep_for=keep,
                             text=line, listener=listener.name, place=c.place, time=self.clock())

        for c in conversations:
            if not c.lines:
                continue
            transcript = "\n".join(c.lines)
            for p, o in ((c.a, c.b), (c.b, c.a)):
                p.current_action = f"talking with {o.name}"
                if p.tier == "hero":
                    p.memory.queue_add(f"{p.name} talked with {o.name}. Conversation:\n{transcript}", "chat", self.tick)
                else:
                    first = next((ln.split(": ", 1)[1] for ln in c.lines if ln.startswith(o.name + ":")), "")
                    p.memory.add(self.tick, "dialogue",
                                 f"Talked with {o.name} at {c.place}." + (f' They said: "{first}"' if first else ""),
                                 with_hero=o.tier == "hero")
                    if o.tier == "hero":
                        p.hero_interactions += 1

    # --- MEMORY --------------------------------------------------------------------------------------

    async def _memory_wave(self):
        """Score every hero memory queued so far this tick."""
        pending = [(h, h.memory.drain_pending()) for h in self.heroes]
        pending = [(h, items) for h, items in pending if items]
        if not pending:
            return
        rate = [(h, [n for n, needs in items if needs]) for h, items in pending]
        rate = [(h, nodes) for h, nodes in rate if nodes]
        requests = [self._request(h, prompts.importance([n.description for n in nodes]), "importance",
                                  prompts.importance_schema(len(nodes)), ccfg.TOKENS_IMPORTANCE, 0.0)
                    for h, nodes in rate]
        all_nodes = [(h, n) for h, items in pending for n, _ in items]
        results, vectors = await asyncio.gather(self.gw.generate_many(requests),
                                                self.gw.embed_many([n.description for _, n in all_nodes]))
        for (h, nodes), r in zip(rate, results):
            ratings = (r.data or {}).get("ratings", []) if r.ok else []
            for i, n in enumerate(nodes):
                value = ratings[i] if i < len(ratings) and isinstance(ratings[i], (int, float)) else 5
                n.importance = float(max(1, min(10, value)))
        for (h, n), vector in zip(all_nodes, vectors):
            h.memory.set_embedding(n, vector)
            if n.kind == "observation":
                h.memory.importance_since_reflection += n.importance
            # The embedding rides along as the node's compact float32 array;
            # it becomes a JSON list only when the hero's slice is saved.
            recorder.log("memory", n.created_tick, agent=h.name, tier="hero", memory_kind=n.kind,
                         importance=n.importance, text=n.description, embedding=n.embedding, evidence=n.evidence)

    # --- REFLECT --------------------------------------------------------------------------------------

    async def _reflect_wave(self):
        due = [h for h in self.heroes if h.memory.importance_since_reflection >= REFLECTION_IMPORTANCE_THRESHOLD]
        if not due:
            return
        requests = [self._request(h, prompts.focal_points(
            h, [m.description for m in h.memory.recent(REFLECTION_LOOKBACK, kinds=("observation",))],
            REFLECTION_NUM_FOCAL_POINTS), "focal", prompts.FOCAL_SCHEMA, ccfg.TOKENS_FOCAL, 0.6) for h in due]
        results = await self.gw.generate_many(requests)
        pairs = []
        for h, r in zip(due, results):
            questions = [str(q).strip() for q in (r.data or {}).get("questions", []) if str(q).strip()] if r.ok else []
            questions = questions[:REFLECTION_NUM_FOCAL_POINTS] or [f"What matters most to {h.name} right now?"]
            for q in questions:
                self._log("focal", h, text=q)
                pairs.append((h, q))
        vectors = await self.gw.embed_many([q for _, q in pairs])
        batch = []
        for (h, q), vec in zip(pairs, vectors):
            nodes = h.memory.retrieve_embedded(vec, self.tick, k=10)
            if nodes:
                batch.append((h, q, nodes))
        results = await self.gw.generate_many([
            self._request(h, prompts.insights(h, q, [n.description for n in nodes], REFLECTION_INSIGHTS_PER_FOCAL_POINT),
                          "insight", prompts.INSIGHT_SCHEMA, ccfg.TOKENS_INSIGHT, 0.6) for h, q, nodes in batch])
        for (h, q, nodes), r in zip(batch, results):
            for item in (r.data or {}).get("insights", []) if r.ok else []:
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                evidence = [nodes[i].id for i in item.get("because", []) if isinstance(i, int) and 0 <= i < len(nodes)]
                self._log("insight", h, text=text, evidence=evidence)
                h.memory.queue_add(text, "reflection", self.tick, evidence=evidence)
        for h in due:
            h.memory.importance_since_reflection = 0.0
            self._log("reflect_pause", h)
        await self._memory_wave()

    # --- PROMOTE ---------------------------------------------------------------------------------------

    async def _promote_wave(self):
        """Background residents who've now dealt with heroes
        `promote_after` times, plus any picked in the UI, become heroes --
        up to the profile's hero cap. Their ring-buffer memories become
        MemoryNodes, embedded in one batch; they plan at the next tick."""
        requested = []
        while self.promotion_requests:
            requested.append(self.promotion_requests.popleft())
        by_name = {b.name: b for b in self.background}
        picks = [by_name[n] for n in dict.fromkeys(requested) if n in by_name]
        picks += [b for b in self.background if b.hero_interactions >= self.promote_after and b not in picks]
        picks = picks[:max(0, self.hero_cap - len(self.heroes))]
        if picks:
            texts = [e.text for b in picks for e in b.memory.entries]
            vectors = iter(await self.gw.embed_many(texts))
            for b in picks:
                hero = promote(b, [next(vectors) for _ in b.memory.entries], self.places)
                self.background.remove(b)
                self.heroes.append(hero)
                self.colors[hero.name] = display.agent_hex_colors([hero.name])[hero.name]
                recorder.add_hero({"name": hero.name, "color": self.colors[hero.name], "age": hero.age,
                                   "traits": hero.traits, "location": hero.location, "tier": "hero",
                                   "promoted_from": b.id})
                why = "picked in the UI" if b.name in requested else f"{b.hero_interactions} dealings with heroes"
                recorder.log("promotion", self.tick, agent=hero.name, tier="hero",
                             text=f"{hero.name} ({b.occupation}) becomes a hero: {why}", resident_id=b.id)
            self._index_places()
        recorder.set_meta(notable=self.notable())

    def notable(self, n: int = 12) -> list:
        """Background residents most tangled up with the heroes, for the
        node's promote list."""
        ranked = sorted(self.background, key=lambda b: (-b.hero_interactions, -sum(b.acquaintances.values()), b.id))
        return [{"name": b.name, "occupation": b.occupation, "location": b.location_label(),
                 "hero_interactions": b.hero_interactions} for b in ranked[:n]]

    def _record_summary(self, hero_encounters: int, conversations: int):
        """The background tier's per-tick aggregate: who is where (the
        busiest places), and how much happened."""
        occupancy = []
        for place, people in self._by_place.items():
            if place.startswith("~"):
                continue
            heroes = sum(1 for p in people if p.tier == "hero")
            occupancy.append({"place": place, "heroes": heroes, "background": len(people) - heroes})
        occupancy.sort(key=lambda o: (-(o["heroes"] + o["background"]), o["place"]))
        off_map = sum(len(people) for place, people in self._by_place.items() if place.startswith("~"))
        busiest = ", ".join(f"{o['place']} {o['heroes'] + o['background']}" for o in occupancy[:3])
        recorder.log("tick_summary", self.tick, tier=None, time=self.clock(),
                     text=f"{self.clock()}: {busiest or 'nobody out'}; {off_map} at home or across town; "
                          f"{hero_encounters} hero encounters, {conversations} conversations",
                     occupancy=occupancy[:20], off_map=off_map, hero_encounters=hero_encounters,
                     conversations=conversations)

    # --- metrics -----------------------------------------------------------------------------------------

    def _record_metrics(self, seconds: float, encounters: int, conversations: int):
        waves = self._wave_metrics
        total = collections.Counter()
        by_tier = collections.Counter()
        by_kind = collections.Counter()
        for w in waves.values():
            for k in ("requests", "tokens_in", "tokens_out", "retries", "failures", "repairs", "backpressure"):
                total[k] += w[k]
            by_tier.update(w["by_tier"])
            by_kind.update(w["by_kind"])
        n_heroes, n_bg = len(self.heroes), len(self.background)
        metrics = {
            "seconds": round(seconds, 3),
            "waves": {k: v["seconds"] for k, v in waves.items()},
            "requests": total["requests"], "tokens_in": total["tokens_in"], "tokens_out": total["tokens_out"],
            "retries": total["retries"], "failures": total["failures"], "repairs": total["repairs"],
            "backpressure": total["backpressure"],
            "tokens_per_second": round(total["tokens_out"] / seconds, 1) if seconds else 0.0,
            "calls_by_tier": dict(by_tier), "calls_by_kind": dict(by_kind),
            "calls_per_hero": round(by_tier.get("hero", 0) / n_heroes, 3) if n_heroes else 0.0,
            "calls_per_background": round(by_tier.get("background", 0) / n_bg, 4) if n_bg else 0.0,
            "heroes": n_heroes, "background": n_bg, "encounters": encounters, "conversations": conversations,
        }
        self.metrics_history.append(metrics)
        recorder.log("metrics", self.tick, tier=None, time=self.clock(),
                     text=f"tick {self.tick + 1}: {metrics['seconds']}s, {metrics['requests']} requests, "
                          f"{metrics['tokens_per_second']} tok/s", **metrics)


def promote(b: BackgroundAgent, vectors: list, places: list) -> CityHero:
    """A background resident as a hero: same name and life, their ring
    buffer turned into MemoryNodes (heuristic importance kept, `vectors`
    from one embed_many batch), standing where they were."""
    from ..memory import MemoryNode
    from .tiers import _ids, compact_vector
    location = b.location if b.location in places else (b.work or b.haunt or f"{b.name}'s place")
    hero = CityHero(name=b.name, age=b.age, traits=b.occupation, currently=b.bio, location=location,
                    home=b.home or b.work or location)
    for e, vector in zip(b.memory.entries, vectors):
        hero.memory.nodes.append(MemoryNode(
            id=next(_ids), kind="chat" if e.kind == "dialogue" else "observation", description=e.text,
            created_tick=e.tick, last_accessed_tick=e.tick, importance=e.importance,
            embedding=compact_vector(vector)))
    hero.acquaintances = b.acquaintances.copy()
    hero.current_action = b.current_action
    hero.promoted_from = b.id
    return hero


class _Conversation:
    __slots__ = ("a", "b", "place", "topic", "lines", "ended", "memories")

    def __init__(self, a, b, place: str, topic: str):
        self.a, self.b, self.place, self.topic = a, b, place, topic
        self.lines = []
        self.ended = False
        self.memories = {}


def _label(place: str, agent) -> str:
    if place == HOME:
        return "home"
    if place == ELSEWHERE:
        return "somewhere across town"
    if place.startswith("~"):
        return "home" if "home" in place else "somewhere across town"
    return place
