"""Entry point: spins up a couple of example personas in a shared location
and runs a short simulation.

Usage:
    python3 main.py [--ticks N] [--chat-model NAME] [--embed-model NAME]
"""

import argparse
import sys

import config
import llm
from agent import Agent
from world import World


def build_default_agents() -> list[Agent]:
    oswald = Agent(
        name="Oswald",
        age=58,
        traits="seasoned bartender, patient, likeable, quiet, a good listener.",
        currently="cleaning glasses in the bar, getting ready for the evening",
        location="Ozzy's Bar",
        wake_up_hour=10,
    )
    lou = Agent(
        name="Lou",
        age=45,
        traits="down on his luck privage eye detective, cynical, lonely, alcoholic",
        currently="nursing a hangover at Ozzy's Bar",
        location="Ozzy's Bar",
        wake_up_hour=12,
    )
    return [oswald, lou]


def main():
    parser = argparse.ArgumentParser(description="Barebones generative agents demo")
    parser.add_argument("--ticks", type=int, default=8, help="number of simulation steps")
    parser.add_argument("--chat-model", default=config.CHAT_MODEL)
    parser.add_argument("--embed-model", default=config.EMBED_MODEL)
    parser.add_argument("--tick_sleep", type=int, default=0, help="seconds to wait between ticks to make it readable")
    args = parser.parse_args()

    config.CHAT_MODEL = args.chat_model
    config.EMBED_MODEL = args.embed_model

    try:
        llm.check_connection()
    except RuntimeError as e:
        print(f"Setup problem: {e}", file=sys.stderr)
        sys.exit(1)

    agents = build_default_agents()
    world = World(agents, tick_sleep=args.tick_sleep)

    print(f"Running {args.ticks} ticks with chat model '{config.CHAT_MODEL}' "
          f"and embed model '{config.EMBED_MODEL}'...\n")
    world.run(args.ticks)

    print("\n--- Memory streams ---")
    for agent in agents:
        print(f"\n{agent.name}:")
        for node in agent.memory.nodes:
            tag = f"[{node.kind}]"
            print(f"  {tag:12s} (importance {node.importance:>4.1f}) {node.description}")


if __name__ == "__main__":
    main()
