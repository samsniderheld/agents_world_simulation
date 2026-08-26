"""Entry point: procedurally generates a small city, spins up a couple of
example personas inside it, and runs a short simulation.

Usage:
    python3 main.py [--ticks N] [--chat-model NAME] [--embed-model NAME] [--map]
"""

import argparse
import sys

import config
import llm
from agent import Agent
from city import City, generate_small_city
from world import World


def build_city() -> City:
    """Procedurally lay out a small two-building city (see city.py) that
    Oswald and Lou live and move around in."""
    return generate_small_city(
        [("Ozzy's Bar", 2), ("Riverside Apartments", 3)],
        width=config.CITY_WIDTH,
        height=config.CITY_HEIGHT,
        seed=7,
    )


def build_default_agents(city: City) -> list[Agent]:
    """Spawn the two example personas just inside the bar's front door."""
    bar_entry = city.entry_point("Ozzy's Bar")
    apt_entry = city.entry_point("Riverside Apartments")
    oswald = Agent(
        name="Oswald",
        age=58,
        traits="seasoned bartender, patient, likeable, quiet, a good listener.",
        currently="cleaning glasses in the bar, getting ready for the evening",
        pos=bar_entry,
        wake_up_hour=10,
    )
    lou = Agent(
        name="Lou",
        age=45,
        traits="down on his luck privage eye detective, cynical, lonely, alcoholic",
        currently="just is just leaving his apartment to get a drink at the Ozzy's Bar",
        pos=apt_entry,
        wake_up_hour=12,
    )
    return [oswald, lou]


def main():
    parser = argparse.ArgumentParser(description="Barebones generative agents demo")
    parser.add_argument("--ticks", type=int, default=8, help="number of simulation steps")
    parser.add_argument("--chat-model", default=config.CHAT_MODEL)
    parser.add_argument("--embed-model", default=config.EMBED_MODEL)
    parser.add_argument("--tick_sleep", type=int, default=0, help="seconds to wait between ticks to make it readable")
    parser.add_argument("--map", action="store_true", help="print an ASCII map snapshot after every tick")
    args = parser.parse_args()

    config.CHAT_MODEL = args.chat_model
    config.EMBED_MODEL = args.embed_model

    try:
        llm.check_connection()
    except RuntimeError as e:
        print(f"Setup problem: {e}", file=sys.stderr)
        sys.exit(1)

    city = build_city()
    agents = build_default_agents(city)
    world = World(agents, city, tick_sleep=args.tick_sleep, show_map=args.map)

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
