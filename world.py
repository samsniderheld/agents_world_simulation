"""A minimal tick-based simulation loop.

Deliberately skips the original's spatial pathfinding/maze -- agents here
have a fixed location for the whole run. Put agents that should be able to
meet and talk in the same location string when you construct them; that's
the one simplification that matters for whether dialogue ever triggers.
Each tick: agents advance their plan, perceive each other, may react
(including breaking into conversation), and are checked for reflection.
"""

import datetime
import time

import planning
import reflection
from agent import Agent
from config import TICK_MINUTES

_DIALOGUE_HINTS = ("talk", "chat", "greet", "ask", "convers", "say hi", "wave")


class World:
    def __init__(self, agents: list[Agent], start_time: datetime.datetime = None, tick_sleep = 0):
        self.agents = agents
        self.start_time = start_time or datetime.datetime(2026, 8, 24, 6, 0)
        self.tick = 0
        self.tick_sleep = tick_sleep
        self.log: list[str] = []

    @property
    def current_time(self) -> datetime.datetime:
        return self.start_time + datetime.timedelta(minutes=TICK_MINUTES * self.tick)

    def _say(self, line: str):
        stamped = f"[{self.current_time.strftime('%I:%M %p')}] {line}"
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
        a.chatting_with, b.chatting_with = b, a
        history: list[str] = []
        speaker, listener = a, b
        for _ in range(max_turns):
            line = speaker.converse_turn(listener, history, self.tick)
            history.append(f"{speaker.name}: {line}")
            self._say(f"{speaker.name}: {line}")
            speaker, listener = listener, speaker
            time.sleep(self.tick_sleep)

        transcript = "\n".join(history)
        for participant, other in ((a, b), (b, a)):
            participant.memory.add(
                f"{participant.name} talked with {other.name}. Conversation:\n{transcript}",
                kind="chat",
                tick=self.tick,
            )
            participant.chatting_with = None
            participant.current_action = f"talking with {other.name}"

    def step(self):
        acting_agents = [a for a in self.agents if a.chatting_with is None]

        for agent in acting_agents:
            planning.next_action(agent, self.tick)
            self._say(f"{agent.name} ({agent.location}): {agent.current_action}")
            agent.memory.add(
                f"{agent.name} is {agent.current_action}", kind="observation", tick=self.tick
            )
            time.sleep(self.tick_sleep)

        for a, b in self._co_located_pairs():
            observation = f"{b.name} is nearby, currently: {b.current_action}."
            reacted = a.react(observation, self.tick)
            if reacted and any(hint in a.current_action.lower() for hint in _DIALOGUE_HINTS):
                self._run_conversation(a, b)

        for agent in self.agents:
            if reflection.reflect(agent, self.tick):
                self._say(f"{agent.name} pauses to reflect.")
                time.sleep(self.tick_sleep)

        self.tick += 1

    def run(self, ticks: int):
        for _ in range(ticks):
            self.step()
