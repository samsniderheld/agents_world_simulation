"""Pure ASCII rendering of one z-level of a City, with agents drawn on top.

Deliberately just a function that returns a string -- it doesn't print
anything or know about the simulation loop, so a future live/curses viewer
can call it repeatedly to redraw the screen instead of relying on
World's own print-per-tick snapshots.
"""

from city import City


def render_level(city: City, agents: list, z: int) -> str:
    """Render z-level `z` of `city` as an ASCII grid, marking each agent
    currently on that level with the first letter of its name, followed by
    a legend and a coordinate list for the agents shown."""
    grid = [row[:] for row in city.grid[z]]

    agents_here = [a for a in agents if a.pos[2] == z]
    for agent in agents_here:
        x, y, _ = agent.pos
        if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
            grid[y][x] = agent.name[0].upper()

    header = f"-- z={z} " + "-" * max(0, city.width - 6)
    lines = ["".join(row) for row in grid]
    legend = "legend: # wall  . floor/street  + door  ^ stairs  letters = agents"
    positions = ", ".join(
        f"{a.name[0].upper()}={a.name}@{a.pos}" for a in agents_here
    ) or "(no agents on this level)"

    return "\n".join([header, *lines, legend, positions])


def render_levels_with_agents(city: City, agents: list) -> str:
    """Render every z-level that currently has at least one agent on it,
    stacked top to bottom, so a tick's output shows exactly the floors
    that matter without printing empty levels."""
    levels = sorted({a.pos[2] for a in agents})
    return "\n\n".join(render_level(city, agents, z) for z in levels)
