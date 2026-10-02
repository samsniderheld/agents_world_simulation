"""A minimal tick-based simulation loop.

Deliberately skips real pathfinding/travel-time simulation -- an agent can
relocate at most once per broad plan step (see planning.decompose's WHERE
line), teleporting there instantly rather than spending ticks in transit.
Co-location is still just a location-string equality check
(_co_located_pairs below), it's just no longer static: a plan can carry an
agent into another agent's location and trigger a meeting that was never
scripted into the starting roster. Each tick: agents advance their plan
(and may relocate as part of that), perceive each other, may react
(including breaking into conversation), and are checked for reflection.

Concurrency: planning and reflection are independent per agent, so both
phases run one agent per thread. The perceive/react phase runs one
*location* per thread: agents only ever interact with others at the same
place, so locations are independent; within one, pairs stay sequential
(a co-located trio produces pairs that share an agent, e.g. (a,b) and
(a,c), and both react() and a conversation mutate that agent). Memories
added during a phase are scored in one batch per agent when it ends
(MemoryStream.flush). How many model calls actually run at once is capped
per backend in llm.py.
"""

import datetime
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import theme

from . import display
from . import llm
from . import planning
from . import recorder
from . import reflection
from .agent import Agent
from .config import TICK_MINUTES
from .textutil import directive_block

_DIALOGUE_HINTS = ("talk", "chat", "greet", "ask", "convers", "say hi", "wave")


def clock_label(start: datetime.datetime, when: datetime.datetime, tick_minutes: int) -> str:
    """"06:00 AM", prefixed with the day number ("Day 3, 06:00 AM") once
    that's more than day 1 or a tick is a day long. Shared with
    treatment.py, which rebuilds dialogue timestamps the same way."""
    time = when.strftime("%I:%M %p")
    day = (when.date() - start.date()).days + 1
    return f"Day {day}, {time}" if day > 1 or tick_minutes >= 1440 else time


class World:
    def __init__(self, agents: list[Agent], start_time: datetime.datetime = None,
                 tick_sleep: int = 0, verbose: bool = False,
                 stop_flag: threading.Event = None, known_places: list = None,
                 anchored_agents: set = None, directive: str = None, tick_minutes: int = None):
        self.agents = agents
        self.start_time = start_time or datetime.datetime(2026, 8, 24, 6, 0)
        self.tick = 0
        self.tick_sleep = tick_sleep
        self.verbose = verbose
        self.stop_flag = stop_flag or threading.Event()
        self.known_places = known_places or []
        # Free-text scene guidance from the Simulation node's own text
        # input -- passed straight through to every plan/decompose/react/
        # dialogue call this run makes (see textutil.directive_block).
        self.directive = directive
        # Simulated minutes per tick -- the Simulation node's setting, falling
        # back to config.TICK_MINUTES. Drives the clock and the length each
        # planned substep is asked to fill (see planning.decompose).
        self.tick_minutes = tick_minutes or TICK_MINUTES
        # Names of agents who must stay exactly where they were placed for
        # the whole run (simulation.py's convene_at) -- decompose()'s WHERE
        # prompt is only ever skipped by handing it an empty/single-item
        # known_places (see planning._where_prompt_block's own early-out),
        # so an anchored agent simply never gets offered anywhere else to
        # be, rather than being asked and trusted to say no.
        self.anchored_agents = anchored_agents or set()
        self.total_ticks = None   # set by run()
        self.until = None
        self.agent_colors = display.agent_colors([a.name for a in agents])
        self.log: list[str] = []
        self._log_lock = threading.Lock()

    @property
    def current_time(self) -> datetime.datetime:
        """The simulated wall-clock time for the current tick."""
        return self.start_time + datetime.timedelta(minutes=self.tick_minutes * self.tick)

    def clock(self) -> str:
        """The current time as shown in logs and prompts -- "06:00 AM", or
        "Day 3, 06:00 AM" once a run can span more than one day."""
        return clock_label(self.start_time, self.current_time, self.tick_minutes)

    def _say(self, line: str):
        """Print one log line stamped with the current simulated time, and
        keep it in self.log for later inspection. Called from multiple
        agent threads during the parallel phases, so self.log is guarded."""
        stamped = f"[{self.clock()}] {line}"
        with self._log_lock:
            self.log.append(stamped)
        print(stamped)

    def _co_located_pairs(self):
        pairs = []
        for i, a in enumerate(self.agents):
            for b in self.agents[i + 1:]:
                if a.location == b.location and a is not b.chatting_with and b is not a.chatting_with:
                    pairs.append((a, b))
        return pairs

    def _run_conversation(self, a: Agent, b: Agent, max_turns: int = 6):
        """The whole exchange in one model call (it used to be one call per
        line, six in a row): both people's identities, what each remembers
        about the other, and the scene. The reply's "Name: line" lines are
        logged as dialogue events one by one, exactly as before, and the
        full transcript is stored as a single 'chat' memory in both."""
        a.chatting_with, b.chatting_with = b, a
        t = theme.current()
        about = {}
        for speaker, other in ((a, b), (b, a)):
            memories = speaker.memory.retrieve(f"{other.name}: a conversation with {other.name}", self.tick, k=5)
            about[speaker.name] = ("\n".join(f"- {m.description}" for m in memories)
                                   or t.template("scene.conversation_no_memories"))
        prompt = t.prompt(
            "scene.conversation", place=a.location, a_name=a.name, a_identity=a.identity_summary(),
            a_doing=a.current_action, a_memories=about[a.name], b_name=b.name, b_identity=b.identity_summary(),
            b_doing=b.current_action, b_memories=about[b.name], directive_block=directive_block(self.directive),
            max_turns=max_turns)
        reply = llm.complete(prompt, temperature=0.8)
        lines = _parse_conversation(reply, a, b)[:max_turns]

        history: list[str] = []
        for speaker, text in lines:
            listener = b if speaker is a else a
            history.append(f"{speaker.name}: {text}")
            self._say(f"{speaker.name}: {text}")
            recorder.log("dialogue", self.tick, agent=speaker.name, text=text, listener=listener.name)
        time.sleep(self.tick_sleep)

        transcript = "\n".join(history)
        for participant, other in ((a, b), (b, a)):
            if history:
                participant.memory.add(
                    f"{participant.name} talked with {other.name}. Conversation:\n{transcript}",
                    kind="chat",
                    tick=self.tick,
                    agent_name=participant.name, color=self.agent_colors[participant.name],
                    verbose=self.verbose,
                )
            participant.chatting_with = None
            participant.current_action = f"talking with {other.name}"

    def _act(self, agent: Agent):
        """One agent's plan/decompose turn for this tick -- runs on its own
        thread alongside every other acting agent's, see class docstring."""
        other_names = [a.name for a in self.agents if a is not agent]
        color = self.agent_colors[agent.name]
        known_places = [] if agent.name in self.anchored_agents else self.known_places
        planning.next_action(agent, self.tick, known_names=other_names, known_places=known_places,
                              verbose=self.verbose, color=color, directive=self.directive,
                              tick_minutes=self.tick_minutes,
                              now=self.clock(), total_ticks=self.total_ticks, until=self.until)
        self._say(f"{agent.name} ({agent.location}): {agent.current_action}")
        recorder.log("action", self.tick, agent=agent.name,
                     text=agent.current_action, location=agent.location,
                     time=self.clock())
        agent.memory.add(
            f"{agent.name} is {agent.current_action}", kind="observation", tick=self.tick,
            agent_name=agent.name, color=color, verbose=self.verbose,
        )
        agent.memory.flush()

    def _maybe_reflect(self, agent: Agent):
        """One agent's reflection check for this tick -- also independent
        per agent, so it runs concurrently across agents."""
        if reflection.reflect(agent, self.tick, verbose=self.verbose,
                               color=self.agent_colors[agent.name]):
            self._say(f"{agent.name} pauses to reflect.")
            recorder.log("reflect_pause", self.tick, agent=agent.name)
        agent.memory.flush()

    def _meet(self, pairs: list):
        """One location's perceive/react/conversation pass for this tick.
        _co_located_pairs() is computed once per tick, but _run_conversation
        resets chatting_with to None as soon as it finishes -- so without the
        already_talked guard, an agent free again after one conversation
        could immediately start a second (and a third...) with every other
        pair it appears in, all stamped with the same tick. One conversation
        per agent per tick."""
        already_talked = set()
        for a, b in pairs:
            if a in already_talked or b in already_talked:
                continue
            observation = f"{b.name} is nearby, currently: {b.current_action}."
            other_names = [x.name for x in self.agents if x is not a]
            reacted = a.react(observation, self.tick, known_names=other_names,
                               verbose=self.verbose, color=self.agent_colors[a.name], directive=self.directive)
            if reacted and any(hint in a.current_action.lower() for hint in _DIALOGUE_HINTS):
                self._run_conversation(a, b)
                already_talked.add(a)
                already_talked.add(b)
        for agent in {x for pair in pairs for x in pair}:
            agent.memory.flush()

    def step(self):
        acting_agents = [a for a in self.agents if a.chatting_with is None]

        if acting_agents:
            with ThreadPoolExecutor(max_workers=len(acting_agents)) as pool:
                list(pool.map(self._act, acting_agents))

        # Perceive/react, one location per thread (see the module docstring).
        by_location = defaultdict(list)
        for a, b in self._co_located_pairs():
            by_location[a.location].append((a, b))
        if by_location:
            with ThreadPoolExecutor(max_workers=len(by_location)) as pool:
                list(pool.map(self._meet, by_location.values()))

        if self.agents:
            with ThreadPoolExecutor(max_workers=len(self.agents)) as pool:
                list(pool.map(self._maybe_reflect, self.agents))

        self.tick += 1

    def run(self, ticks: int):
        # Agents plan for exactly this stretch (planning.generate_plan).
        self.total_ticks = ticks
        end = self.start_time + datetime.timedelta(minutes=self.tick_minutes * ticks)
        self.until = clock_label(self.start_time, end, self.tick_minutes)
        for _ in range(ticks):
            if self.stop_flag.is_set():
                break
            self.step()


def _parse_conversation(reply: str, a: Agent, b: Agent) -> list:
    """(speaker, text) pairs from "Name: line" lines. A label matches an
    agent by full name, or by first name / any word of it (a model may
    write "Augie:" for 'Auguste "Augie" Worthington'); an unmatched label
    alternates from whoever spoke last. Quotes and bracketed stage
    directions are stripped; lines without a label are skipped."""
    def matches(label: str, agent: Agent) -> bool:
        label = label.strip().strip('*"').lower()
        name = agent.name.lower()
        words = {w.strip('"') for w in name.split()}
        return label == name or label in words or label.split()[0] in words

    out, last = [], None
    for raw in reply.splitlines():
        if ":" not in raw:
            continue
        label, text = raw.split(":", 1)
        label = re.sub(r"^[\s\-*\d.)]+", "", label)
        text = re.sub(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*", "", text).strip().strip('"').strip()
        if not text or len(label) > 60:
            continue
        speaker = a if matches(label, a) else b if matches(label, b) else (b if last is a else a)
        out.append((speaker, text))
        last = speaker
    return out
