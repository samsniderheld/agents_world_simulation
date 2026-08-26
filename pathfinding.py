"""Shortest-path movement through a City's tile grid: ordinary horizontal
steps on the same z-level, plus the vertical links (doors, stairwells) a
City registers between z-levels.
"""

from collections import deque

from city import City


def find_path(city: City, start: tuple, goal: tuple):
    """Breadth-first search from `start` to `goal` (both (x, y, z) tuples).
    Returns the path as a list of positions from start to goal inclusive,
    or None if goal is unreachable."""
    if start == goal:
        return [start]

    frontier = deque([start])
    came_from = {start: None}
    while frontier:
        current = frontier.popleft()
        if current == goal:
            break
        for nxt in _neighbors(city, current):
            if nxt not in came_from:
                came_from[nxt] = current
                frontier.append(nxt)

    if goal not in came_from:
        return None

    path = []
    node = goal
    while node is not None:
        path.append(node)
        node = came_from[node]
    path.reverse()
    return path


def _neighbors(city: City, pos: tuple):
    """Yield every position reachable from `pos` in one step: the four
    walkable horizontal neighbors on the same z-level, plus any z-level
    change available via the city's registered vertical links."""
    x, y, z = pos
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if city.is_walkable(nx, ny, z):
            yield (nx, ny, z)
    for other in city.vertical_links.get(pos, ()):
        yield other
