"""The Agent: identity + memory stream + perceive/react behavior.
(Conversations are written whole by world.py's _run_conversation.)"""

import theme

from . import display
from . import llm
from . import recorder
from .memory import MemoryStream
from .textutil import cast_constraint, directive_block


class Agent:
    def __init__(self, name: str, age: int, traits: str, currently: str,
                 location: str):
        self.name = name
        self.age = age
        self.traits = traits          # e.g. "creative, warm, a bit scattered"
        self.currently = currently    # e.g. "trying to finish a mural before Friday"
        self.location = location

        self.memory = MemoryStream()
        self.plan: list[str] = []      # the whole run's plan, broad items in order
        self.plan_bounds: list = []    # (first tick, end tick) each item covers
        self.current_item = -1         # index into plan of the decomposed item
        self.substeps: list[str] = []  # that item, one action per tick
        self.current_action: str = "idle"
        self.chatting_with: "Agent | None" = None

    def identity_summary(self) -> str:
        # self.location matters here, not just as event metadata -- this
        # string feeds every LLM call an agent makes (daily plan, decompose,
        # react, dialogue), and until now none of them ever mentioned where
        # the agent currently is. That was invisible for an ordinary run
        # (an agent's bio-grounded `currently` and `location` already imply
        # the same place), but a convened run intentionally puts an agent
        # somewhere their bio has nothing to say about -- without this line,
        # the model had zero signal of that and just narrated `currently`'s
        # habitual routine as if they were still wherever that normally
        # happens, producing text totally disconnected from the tagged
        # location.
        return theme.current().prompt("scene.identity", name=self.name, age=self.age, traits=self.traits,
                                      currently=self.currently, location=self.location)

    def perceive(self, observation: str, tick: int):
        """Record something the agent has noticed as a new memory."""
        self.memory.add(observation, kind="observation", tick=tick)

    def react(self, observation: str, tick: int, known_names: list = None,
              verbose: bool = False, color: str = "", directive: str = None) -> bool:
        """Decide whether `observation` warrants deviating from the current
        plan. Returns True if the agent should react (and updates
        current_action accordingly); False if it just continues its plan.
        `known_names` should be every other agent's name, so the reaction
        doesn't invent a new named character. When `verbose`, prints the
        observation and the resulting decision to the terminal right as
        each is generated (see display.py); `color` is this agent's
        assigned display color. `directive` is the Simulation node's
        free-text scene guidance, if any (see textutil.directive_block).
        """
        if verbose:
            print(display.observation_line(self.name, color, observation))
        recorder.log("observe", tick, agent=self.name, text=observation)

        memories = self.memory.retrieve(observation, tick, k=6)
        t = theme.current()
        memory_text = "\n".join(f"- {m.description}" for m in memories) or t.template("scene.react_no_memories")

        prompt = t.prompt("scene.react", identity=self.identity_summary(),
                          cast_constraint=cast_constraint(self.name, known_names),
                          directive_block=directive_block(directive), memories=memory_text, name=self.name,
                          action=self.current_action, observation=observation)
        reply = llm.complete(prompt, temperature=0.6)
        self.memory.add(f"Observed: {observation}", kind="observation", tick=tick,
                         agent_name=self.name, color=color, verbose=verbose)

        if reply.strip().upper().startswith("REACT"):
            new_action = reply.split(":", 1)[1].strip() if ":" in reply else reply.strip()
            self.current_action = new_action or self.current_action
            self.memory.add(f"{self.name} decided to: {self.current_action}", kind="observation", tick=tick,
                             agent_name=self.name, color=color, verbose=verbose)
            if verbose:
                print(display.reaction_line(self.name, color, self.current_action))
            recorder.log("react", tick, agent=self.name, text=self.current_action)
            return True

        if verbose:
            print(display.continue_line(self.name, color))
        recorder.log("continue", tick, agent=self.name)
        return False
