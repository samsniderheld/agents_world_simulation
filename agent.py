"""The Agent: identity + memory stream + perceive/react/converse behavior."""

import llm
from memory import MemoryStream
from textutil import first_spoken_line


class Agent:
    def __init__(self, name: str, age: int, traits: str, currently: str,
                 location: str, wake_up_hour: int = 7):
        self.name = name
        self.age = age
        self.traits = traits          # e.g. "creative, warm, a bit scattered"
        self.currently = currently    # e.g. "trying to finish a mural before Friday"
        self.location = location
        self.wake_up_hour = wake_up_hour

        self.memory = MemoryStream()
        self.plan: list[str] = []      # today's broad-strokes plan, in order
        self.plan_cursor = 0
        self.current_action: str = "idle"
        self.chatting_with: "Agent | None" = None

    def identity_summary(self) -> str:
        return (
            f"{self.name} is a {self.age}-year-old. "
            f"Personality: {self.traits}. "
            f"Currently: {self.currently}."
        )

    def perceive(self, observation: str, tick: int):
        self.memory.add(observation, kind="observation", tick=tick)

    def react(self, observation: str, tick: int) -> bool:
        """Decide whether `observation` warrants deviating from the current
        plan. Returns True if the agent should react (and updates
        current_action accordingly); False if it just continues its plan.
        """
        memories = self.memory.retrieve(observation, tick, k=6)
        memory_text = "\n".join(f"- {m.description}" for m in memories) or "(none yet)"

        prompt = (
            f"{self.identity_summary()}\n\n"
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
            f"Write {self.name}'s next line of dialogue only (no name prefix, "
            "one or two sentences). If the conversation feels finished, "
            "write a natural closing line. Output ONLY the spoken words -- "
            "no stage directions, no commentary about the conversation."
        )
        reply = llm.complete(prompt, temperature=0.8)
        return first_spoken_line(reply)
