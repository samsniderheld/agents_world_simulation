"""A minimal tick-based simulation loop.

Deliberately skips spatial pathfinding/maze -- agents here have a fixed
location for the whole run. Put agents that should be able to meet and talk
in the same location string when you construct them; that's the one
simplification that matters for whether dialogue ever triggers. Each tick:
agents advance their plan, perceive each other, may react (including
breaking into conversation), and are checked for reflection.

Planning and reflection are each independent per agent (no shared state is
touched), so both phases run one agent per thread -- real concurrent
"thinking" across agents, not just interleaved logging, which is the whole
point once a frontend is watching events stream in live. The
perceive/react phase stays sequential: a co-located trio produces pairs
that share an agent (e.g. (a,b) and (a,c)), and both react() and a
conversation mutate that shared agent's state.
"""

import datetime
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import display
import planning
import recorder
import reflection
from agent import Agent
from config import TICK_MINUTES

_DIALOGUE_HINTS = ("talk", "chat", "greet", "ask", "convers", "say hi", "wave")


class World:
    def __init__(self, agents: list[Agent], start_time: datetime.datetime = None,
                 tick_sleep: int = 0, verbose: bool = False,
                 stop_flag: threading.Event = None):
        self.agents = agents
        self.start_time = start_time or datetime.datetime(2026, 8, 24, 6, 0)
        self.tick = 0
        self.tick_sleep = tick_sleep
        self.verbose = verbose
        self.stop_flag = stop_flag or threading.Event()
        self.agent_colors = display.agent_colors([a.name for a in agents])
        self.log: list[str] = []
        self._log_lock = threading.Lock()

    @property
    def current_time(self) -> datetime.datetime:
        """The simulated wall-clock time for the current tick."""
        return self.start_time + datetime.timedelta(minutes=TICK_MINUTES * self.tick)

    def _say(self, line: str):
        """Print one log line stamped with the current simulated time, and
        keep it in self.log for later inspection. Called from multiple
        agent threads during the parallel phases, so self.log is guarded."""
        stamped = f"[{self.current_time.strftime('%I:%M %p')}] {line}"
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
        """Alternate converse_turn() calls between two agents for up to
        max_turns lines, logging each line and then storing the full
        transcript as a single 'chat' memory in both agents."""
        a.chatting_with, b.chatting_with = b, a
        history: list[str] = []
        speaker, listener = a, b
        for _ in range(max_turns):
            line = speaker.converse_turn(listener, history, self.tick)
            history.append(f"{speaker.name}: {line}")
            self._say(f"{speaker.name}: {line}")
            recorder.log("dialogue", self.tick, agent=speaker.name, text=line, listener=listener.name)
            speaker, listener = listener, speaker
            time.sleep(self.tick_sleep)

        transcript = "\n".join(history)
        for participant, other in ((a, b), (b, a)):
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
        planning.next_action(agent, self.tick, known_names=other_names,
                              verbose=self.verbose, color=color)
        self._say(f"{agent.name} ({agent.location}): {agent.current_action}")
        recorder.log("action", self.tick, agent=agent.name,
                     text=agent.current_action, location=agent.location,
                     time=self.current_time.strftime("%I:%M %p"))
        agent.memory.add(
            f"{agent.name} is {agent.current_action}", kind="observation", tick=self.tick,
            agent_name=agent.name, color=color, verbose=self.verbose,
        )

    def _maybe_reflect(self, agent: Agent):
        """One agent's reflection check for this tick -- also independent
        per agent, so it runs concurrently across agents."""
        if reflection.reflect(agent, self.tick, verbose=self.verbose,
                               color=self.agent_colors[agent.name]):
            self._say(f"{agent.name} pauses to reflect.")
            recorder.log("reflect_pause", self.tick, agent=agent.name)

    def step(self):
        acting_agents = [a for a in self.agents if a.chatting_with is None]

        if acting_agents:
            with ThreadPoolExecutor(max_workers=len(acting_agents)) as pool:
                list(pool.map(self._act, acting_agents))

        for a, b in self._co_located_pairs():
            observation = f"{b.name} is nearby, currently: {b.current_action}."
            other_names = [x.name for x in self.agents if x is not a]
            reacted = a.react(observation, self.tick, known_names=other_names,
                               verbose=self.verbose, color=self.agent_colors[a.name])
            if reacted and any(hint in a.current_action.lower() for hint in _DIALOGUE_HINTS):
                self._run_conversation(a, b)

        if self.agents:
            with ThreadPoolExecutor(max_workers=len(self.agents)) as pool:
                list(pool.map(self._maybe_reflect, self.agents))

        self.tick += 1

    def run(self, ticks: int):
        for _ in range(ticks):
            if self.stop_flag.is_set():
                break
            self.step()
