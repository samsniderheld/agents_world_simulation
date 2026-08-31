"""Entry point: spins up a couple of example personas in a shared location
and runs a short simulation.

Usage:
    python3 main.py [--ticks N] [--chat-model NAME] [--embed-model NAME] [--context-tokens N] [--verbose] [--no-serve]

By default, once the run finishes it starts a local web server and opens
viewer.html in a browser to inspect the saved run_log.json; pass --no-serve
to skip that and just exit.
"""

import argparse
import functools
import http.server
import os
import socketserver
import sys
import webbrowser

import config
import display
import llm
import recorder
from agent import Agent
from treatment import generate_treatment
from world import World

LOG_FILE = "run_log.json"


def serve_viewer(directory: str):
    """Serve `directory` (viewer.html + run_log.json live here) on a free
    local port and open the viewer in a browser tab. Blocks until Ctrl+C --
    this is the last thing main() does, so the run's results stay
    inspectable until the user is done looking at them."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/viewer.html"
        print(f"Serving results at {url} (Ctrl+C to stop)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def build_default_agents() -> list[Agent]:
    # oswald = Agent(
    #     name="Oswald",
    #     age=58,
    #     traits="seasoned bartender, patient, likeable, quiet, a good listener.",
    #     currently="cleaning glasses in the bar, getting ready for the evening",
    #     location="Ozzy's Bar",
    # )
    lou = Agent(
        name="Lou",
        age=45,
        traits="down on his luck privage eye detective, cynical, lonely, alcoholic",
        currently="nursing a hangover walking around the boardwalk",
        location="The boardwalk",
    )
    # veronica = Agent(
    #     name="Veronica",
    #     age=32,
    #     traits="sultry lounge singer, sharp-tongued, guarded, more dangerous than she lets on",
    #     currently="rehearsing her set for tonight's show at Ozzy's Bar",
    #     location="Ozzy's Bar",
    # )
    # detective_marsh = Agent(
    #     name="Marsh",
    #     age=50,
    #     traits="corrupt police detective, gruff, always working an angle, hides menace behind a friendly voice",
    #     currently="stopping by Ozzy's Bar to collect a favor",
    #     location="Ozzy's Bar",
    # )
    # sal = Agent(
    #     name="Sal",
    #     age=61,
    #     traits="aging mob boss, calm and courteous on the surface, ruthless underneath, expects respect",
    #     currently="holding court in his usual booth at Ozzy's Bar",
    #     location="Ozzy's Bar",
    # )
    # return [oswald, lou, veronica, detective_marsh, sal]
    return[lou]


def main():
    parser = argparse.ArgumentParser(description="Barebones generative agents demo")
    parser.add_argument("--ticks", type=int, default=8, help="number of simulation steps")
    parser.add_argument("--chat-model", default=config.CHAT_MODEL)
    parser.add_argument("--embed-model", default=config.EMBED_MODEL)
    parser.add_argument("--context-tokens", type=int, default=config.CHAT_CONTEXT_TOKENS,
                         help="context window (tokens) requested per chat call, overriding config.CHAT_CONTEXT_TOKENS")
    parser.add_argument("--tick_sleep", type=int, default=0, help="seconds to wait between ticks to make it readable")
    parser.add_argument("--verbose", action="store_true",
                         help="print each agent's observations and reactions as they're generated")
    parser.add_argument("--no-serve", action="store_true",
                         help="don't start the viewer web server after the run finishes")
    args = parser.parse_args()

    config.CHAT_MODEL = args.chat_model
    config.EMBED_MODEL = args.embed_model
    config.CHAT_CONTEXT_TOKENS = args.context_tokens

    try:
        llm.check_connection()
    except RuntimeError as e:
        print(f"Setup problem: {e}", file=sys.stderr)
        sys.exit(1)

    agents = build_default_agents()
    agent_hex_colors = display.agent_hex_colors([a.name for a in agents])
    recorder.start(
        agents=[
            {
                "name": a.name, "color": agent_hex_colors[a.name],
                "age": a.age, "traits": a.traits, "location": a.location,
            }
            for a in agents
        ],
        meta={
            "chat_model": config.CHAT_MODEL, "embed_model": config.EMBED_MODEL,
            "context_tokens": config.CHAT_CONTEXT_TOKENS, "ticks": args.ticks,
        },
    )

    world = World(agents, tick_sleep=args.tick_sleep, verbose=args.verbose)

    print(f"Running {args.ticks} ticks with chat model '{config.CHAT_MODEL}' "
          f"({config.CHAT_CONTEXT_TOKENS} context tokens) and embed model "
          f"'{config.EMBED_MODEL}'...\n")
    world.run(args.ticks)

    print("\n--- Memory streams ---")
    for agent in agents:
        print(f"\n{agent.name}:")
        for node in agent.memory.nodes:
            tag = f"[{node.kind}]"
            print(f"  {tag:12s} (importance {node.importance:>4.1f}) {node.description}")

    print("\n--- Treatment ---")
    treatment = generate_treatment(world.log, [agent.name for agent in agents])
    print(treatment)
    recorder.log("treatment", world.tick, text=treatment)

    recorder.save(LOG_FILE)
    print(f"\nSaved run log to {LOG_FILE}")

    if not args.no_serve:
        serve_viewer(directory=os.path.dirname(os.path.abspath(__file__)) or ".")


if __name__ == "__main__":
    main()
