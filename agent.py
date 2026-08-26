"""The Agent: identity + memory stream + perceive/react/converse behavior."""

import llm
from memory import MemoryStream
from textutil import cast_constraint, first_spoken_line


class Agent:
    def __init__(self, name: str, age: int, traits: str, currently: str,
                 pos: tuple, wake_up_hour: int = 7):
        """Set up identity, an empty memory stream, and starting position.
        `pos` is an (x, y, z) tile coordinate in the World's City -- see
        city.py for how those are generated and city.entry_point() for a
        convenient spawn point inside a named building."""
        self.name = name
        self.age = age
        self.traits = traits          # e.g. "creative, warm, a bit scattered"
        self.currently = currently    # e.g. "trying to finish a mural before Friday"
        self.wake_up_hour = wake_up_hour

        self.pos = pos                 # current (x, y, z) tile
        self.dest: tuple = None        # (x, y, z) the agent is walking toward, or None
        self.path: list = []           # remaining tiles of the current route to dest

        # Kept in sync by World each tick (see World._sync_location_label)
        # so every prompt below knows where the agent actually is on the
        # map, not just what its plan text claims.
        self.location_label: str = "an unspecified location"
        self.dest_label: str = None    # name of the building being walked toward, if any

        self.memory = MemoryStream()
        self.plan: list[str] = []      # today's broad-strokes plan, in order
        self.plan_cursor = 0
        self.current_action: str = "idle"
        self.chatting_with: "Agent | None" = None

    def identity_summary(self) -> str:
        """A short natural-language description of who this agent is and
        where it physically is right now, used as context in every prompt
        sent to the LLM."""
        return (
            f"{self.name} is a {self.age}-year-old. "
            f"Personality: {self.traits}. "
            f"Currently: {self.currently}. "
            f"{self.spatial_status()}"
        )

    def spatial_status(self) -> str:
        """A short line describing where the agent physically is, including
        whether it's still en route somewhere -- this is what lets
        generated text follow the map instead of drifting from it."""
        if self.dest_label and self.dest_label != self.location_label:
            return f"Right now {self.name} is at {self.location_label}, walking toward {self.dest_label} (not there yet)."
        return f"Right now {self.name} is at {self.location_label}."

    def perceive(self, observation: str, tick: int):
        """Record something the agent has noticed as a new memory."""
        self.memory.add(observation, kind="observation", tick=tick)

    def react(self, observation: str, tick: int, known_names: list = None) -> bool:
        """Decide whether `observation` warrants deviating from the current
        plan. Returns True if the agent should react (and updates
        current_action accordingly); False if it just continues its plan.
        `known_names` should be every other agent's name, so the reaction
        doesn't invent a new named character.
        """
        memories = self.memory.retrieve(observation, tick, k=6)
        memory_text = "\n".join(f"- {m.description}" for m in memories) or "(none yet)"

        prompt = (
            f"{self.identity_summary()}\n\n"
            f"{cast_constraint(self.name, known_names)}\n\n"
            f"Relevant memories:\n{memory_text}\n\n"
            f"{self.name}'s current planned action: {self.current_action}\n"
            f"New observation: {observation}\n\n"
            f"Should {self.name} keep doing the planned action, or react to the "
            "observation with something different? "
            "Reply with exactly one line in the form:\n"
            "REACT: <new action description>\n"
            "or:\n"
            "CONTINUE"
        )
        reply = llm.complete(prompt, temperature=0.6)
        self.memory.add(f"Observed: {observation}", kind="observation", tick=tick)

        if reply.strip().upper().startswith("REACT"):
            new_action = reply.split(":", 1)[1].strip() if ":" in reply else reply.strip()
            self.current_action = new_action or self.current_action
            self.memory.add(f"{self.name} decided to: {self.current_action}", kind="observation", tick=tick)
            return True
        return False

    def converse_turn(self, other: "Agent", history: list, tick: int) -> str:
        """Generate this agent's next line in an ongoing conversation."""
        focal = f"a conversation with {other.name}"
        memories = self.memory.retrieve(f"{other.name}: {focal}", tick, k=5)
        memory_text = "\n".join(f"- {m.description}" for m in memories) or "(none yet)"
        convo_text = "\n".join(history) or "(conversation just started)"

        prompt = (
            f"{self.identity_summary()}\n\n"
            f"What {self.name} remembers about {other.name} and related things:\n{memory_text}\n\n"
            f"Conversation so far:\n{convo_text}\n\n"
            f"{self.name} is speaking directly to {other.name} right now, face to "
            f"face -- the memories above may mention other people, but the person "
            f"in front of {self.name} is {other.name} and no one else. If "
            f"{self.name} addresses them by name, it must be \"{other.name}\"; "
            "never substitute a different name from memory.\n\n"
            f"Write {self.name}'s next line of dialogue only (no name prefix, "
            "one or two sentences). If the conversation feels finished, "
            "write a natural closing line. Output ONLY the spoken words -- "
            "no stage directions, no commentary about the conversation."
        )
        reply = llm.complete(prompt, temperature=0.8)
        return first_spoken_line(reply)
