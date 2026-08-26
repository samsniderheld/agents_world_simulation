"""A tick-based simulation loop over a City (see city.py): agents have real
(x, y, z) positions and walk tile-by-tile toward destinations chosen from
their current plan text, using pathfinding.py to route through doors and
stairwells between floors. Each tick: agents advance their plan and their
position, perceive nearby agents, may react (including breaking into
conversation), and are checked for reflection.
"""

import datetime
import time

import pathfinding
import planning
import reflection
from agent import Agent
from city import City
from config import MOVE_SPEED, NEARBY_RADIUS, TICK_MINUTES
from render import render_levels_with_agents

_DIALOGUE_HINTS = ("talk", "chat", "greet", "ask", "convers", "say hi", "wave")


class World:
    def __init__(self, agents: list[Agent], city: City,
                 start_time: datetime.datetime = None, tick_sleep: int = 0,
                 show_map: bool = False):
        """Hold the agents, the City they move through, and the simulated
        clock; `show_map` controls whether an ASCII snapshot of every
        occupied z-level is printed after each tick."""
        self.agents = agents
        self.city = city
        self.start_time = start_time or datetime.datetime(2026, 8, 24, 6, 0)
        self.tick = 0
        self.tick_sleep = tick_sleep
        self.show_map = show_map
        self.log: list[str] = []

    @property
    def current_time(self) -> datetime.datetime:
        """The simulated wall-clock time for the current tick."""
        return self.start_time + datetime.timedelta(minutes=TICK_MINUTES * self.tick)

    def _say(self, line: str):
        """Print one log line stamped with the current simulated time, and
        keep it in self.log for later inspection."""
        stamped = f"[{self.current_time.strftime('%I:%M %p')}] {line}"
        self.log.append(stamped)
        print(stamped)

    def _location_label(self, agent: Agent) -> str:
        """A human-readable description of where an agent is right now,
        derived from its tile position (building + floor, or 'the street')."""
        building = self.city.building_at(agent.pos[0], agent.pos[1])
        if building is None:
            return "the street"
        floor = agent.pos[2]
        return f"{building.name}, floor {floor}" if floor else building.name

    def _sync_location_label(self, agent: Agent):
        """Refresh an agent's cached location/destination labels from its
        actual tile position (see Agent.location_label / Agent.dest_label),
        so every LLM prompt built from identity_summary() reflects where the
        agent really is on the map -- not just whatever its last planned
        action claimed. Without this, an agent mid-walk keeps narrating
        actions from the room it already left."""
        agent.location_label = self._location_label(agent)
        if agent.dest is not None:
            building = self.city.building_at(agent.dest[0], agent.dest[1])
            agent.dest_label = building.name if building else None
        else:
            agent.dest_label = None

    def _update_destination(self, agent: Agent):
        """If the agent's freshly-generated current_action mentions a known
        building by name, point it there. This is a simple keyword match on
        the LLM's free-text action, not real language understanding -- see
        README for the tradeoff."""
        text = agent.current_action.lower()
        for building in self.city.buildings:
            if building.name.lower() in text:
                target = self.city.entry_point(building.name)
                if target != agent.dest:
                    agent.dest = target
                    agent.path = []
                return

    def _advance(self, agent: Agent):
        """Move an agent up to MOVE_SPEED tiles along the path to its
        current destination, computing (or recomputing, if stale) that path
        via pathfinding.find_path as needed."""
        if agent.dest is None:
            return
        if agent.pos == agent.dest:
            agent.dest = None
            agent.path = []
            return

        if not agent.path or agent.path[0] != agent.pos:
            agent.path = pathfinding.find_path(self.city, agent.pos, agent.dest) or []

        for _ in range(MOVE_SPEED):
            if len(agent.path) < 2:
                break
            agent.path.pop(0)
            agent.pos = agent.path[0]

        if agent.pos == agent.dest:
            agent.dest = None

    def _co_located_pairs(self):
        """Every pair of agents on the same z-level within NEARBY_RADIUS
        tiles of each other, excluding any pair already mid-conversation."""
        pairs = []
        for i, a in enumerate(self.agents):
            for b in self.agents[i + 1:]:
                if a is b.chatting_with or b is a.chatting_with:
                    continue
                ax, ay, az = a.pos
                bx, by, bz = b.pos
                if az == bz and max(abs(ax - bx), abs(ay - by)) <= NEARBY_RADIUS:
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

    def render_current(self):
        """Print an ASCII snapshot of every z-level that currently has an
        agent on it."""
        print(render_levels_with_agents(self.city, self.agents))

    def step(self):
        """Run one simulated tick: advance plans and positions, let
        co-located agents perceive and react to each other (possibly
        starting a conversation), check everyone for reflection, then
        optionally print the map."""
        for agent in self.agents:
            self._sync_location_label(agent)

        acting_agents = [a for a in self.agents if a.chatting_with is None]

        for agent in acting_agents:
            other_names = [a.name for a in self.agents if a is not agent]
            planning.next_action(agent, self.tick, known_names=other_names)
            self._update_destination(agent)
            self._sync_location_label(agent)
            self._say(f"{agent.name} ({agent.location_label}): {agent.current_action}")
            agent.memory.add(
                f"{agent.name} is {agent.current_action}", kind="observation", tick=self.tick
            )
            time.sleep(self.tick_sleep)

        for agent in acting_agents:
            self._advance(agent)
            self._sync_location_label(agent)

        for a, b in self._co_located_pairs():
            observation = f"{b.name} is nearby, currently: {b.current_action}."
            other_names = [x.name for x in self.agents if x is not a]
            reacted = a.react(observation, self.tick, known_names=other_names)
            if reacted and any(hint in a.current_action.lower() for hint in _DIALOGUE_HINTS):
                self._run_conversation(a, b)

        for agent in self.agents:
            if reflection.reflect(agent, self.tick):
                self._say(f"{agent.name} pauses to reflect.")
                time.sleep(self.tick_sleep)

        if self.show_map:
            self.render_current()

        self.tick += 1

    def run(self, ticks: int):
        """Run `ticks` simulated ticks in sequence."""
        for _ in range(ticks):
            self.step()
