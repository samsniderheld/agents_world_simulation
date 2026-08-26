"""Procedural small-city generation: a 3D tile grid (x, y, z) with a handful
of buildings placed on a street-level layer, each with a few floors stacked
above it and connected by a door (street <-> floor 1) and an internal
stairwell (floor 1 <-> floor 2 <-> ... <-> floor N).

Dwarf-Fortress-inspired but much simpler: no digging, no terrain, one
z-column per building for vertical movement rather than real staircases.
"""

import random
from collections import defaultdict
from dataclasses import dataclass

WALL = "#"
FLOOR = "."
STREET = "."
DOOR = "+"
STAIR = "^"
VOID = " "

_WALKABLE = {FLOOR, STREET, DOOR, STAIR}


@dataclass
class Building:
    """One building's footprint, floor count, and its two vertical
    connectors (street door, internal stairwell column)."""

    name: str
    x0: int
    y0: int
    x1: int          # exclusive
    y1: int          # exclusive
    floors: int       # floors above street level (z=1..floors)
    door: tuple       # (x, y) at street level
    stair: tuple      # (x, y) reused on every floor

    def contains(self, x: int, y: int) -> bool:
        """True if (x, y) falls inside this building's footprint, at any z."""
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    @property
    def center(self) -> tuple:
        """(x, y) of the middle of the footprint -- used as the default
        'go inside' target."""
        return ((self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2)


class City:
    """The full 3D tile grid plus the buildings placed on it and the
    vertical links (door/stairwell edges) that connect z-levels."""

    def __init__(self, width: int, height: int, max_floors: int):
        """Allocate an empty grid: z=0 is an open street, z=1..max_floors
        start out void (only filled in where a building is carved)."""
        self.width = width
        self.height = height
        self.grid = [self._blank_level(z) for z in range(max_floors + 1)]
        self.buildings: list[Building] = []
        self.vertical_links: dict = defaultdict(list)

    def _blank_level(self, z: int):
        """Build one empty z-level: street tiles at z=0, void everywhere
        else until a building carves floor tiles into it."""
        fill = STREET if z == 0 else VOID
        return [[fill for _ in range(self.width)] for _ in range(self.height)]

    def tile(self, x: int, y: int, z: int) -> str:
        """Return the character at (x, y, z), or VOID if out of bounds."""
        if 0 <= z < len(self.grid) and 0 <= y < self.height and 0 <= x < self.width:
            return self.grid[z][y][x]
        return VOID

    def set_tile(self, x: int, y: int, z: int, ch: str):
        """Write one tile character during generation."""
        self.grid[z][y][x] = ch

    def is_walkable(self, x: int, y: int, z: int) -> bool:
        """True if an agent can stand on (x, y, z) -- floor, street, door,
        or stairwell tiles, but not walls or void."""
        return self.tile(x, y, z) in _WALKABLE

    def add_vertical_link(self, a: tuple, b: tuple):
        """Register a two-way edge between two (x, y, z) positions on
        adjacent z-levels (a door or a stairwell step), used by pathfinding
        alongside ordinary horizontal moves."""
        self.vertical_links[a].append(b)
        self.vertical_links[b].append(a)

    def building_at(self, x: int, y: int):
        """Return the Building whose footprint contains (x, y), or None if
        that's open street."""
        for b in self.buildings:
            if b.contains(x, y):
                return b
        return None

    def building(self, name: str) -> Building:
        """Look up a Building by name (case-insensitive); raises KeyError
        if no building has that name."""
        for b in self.buildings:
            if b.name.lower() == name.lower():
                return b
        raise KeyError(f"no building named {name!r}")

    def entry_point(self, name: str) -> tuple:
        """A walkable spot inside floor 1 of the named building -- the
        default destination when an agent wants to 'go to' this place."""
        b = self.building(name)
        cx, cy = b.center
        return (cx, cy, 1)


def _overlaps(a: tuple, b: tuple, margin: int = 0) -> bool:
    """True if rectangles a and b (each x0, y0, x1, y1) come within `margin`
    tiles of touching -- used to keep generated buildings from crowding."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (
        ax1 + margin <= bx0 or bx1 + margin <= ax0
        or ay1 + margin <= by0 or by1 + margin <= ay0
    )


def _carve_building(city: City, name: str, x0: int, y0: int, x1: int, y1: int,
                     floors: int, rng: random.Random) -> Building:
    """Write walls/floors/door/stairwell tiles for one building into the
    city grid across z=0 (street door) through z=floors, wiring up the
    vertical links that connect them, and return the resulting Building."""
    door_x = rng.randint(x0 + 1, x1 - 2)
    door_y = y1 - 1
    stair_x = rng.randint(x0 + 1, x1 - 2)
    stair_y = rng.randint(y0 + 1, y1 - 2)

    # Street-level footprint: a ring of walls around the lot with one door.
    for y in range(y0, y1):
        for x in range(x0, x1):
            edge = x in (x0, x1 - 1) or y in (y0, y1 - 1)
            city.set_tile(x, y, 0, WALL if edge else FLOOR)
    city.set_tile(door_x, door_y, 0, DOOR)

    # Each floor: same wall ring, plus a stairwell tile linked to the floor
    # below it (or, on floor 1, a door linked down to the street).
    prev_stair_pos = None
    for z in range(1, floors + 1):
        for y in range(y0, y1):
            for x in range(x0, x1):
                edge = x in (x0, x1 - 1) or y in (y0, y1 - 1)
                city.set_tile(x, y, z, WALL if edge else FLOOR)

        if z == 1:
            city.set_tile(door_x, door_y, z, DOOR)
            city.add_vertical_link((door_x, door_y, 0), (door_x, door_y, z))

        city.set_tile(stair_x, stair_y, z, STAIR)
        if prev_stair_pos is not None:
            city.add_vertical_link(prev_stair_pos, (stair_x, stair_y, z))
        prev_stair_pos = (stair_x, stair_y, z)

    building = Building(name, x0, y0, x1, y1, floors, (door_x, door_y), (stair_x, stair_y))
    city.buildings.append(building)
    return building


def generate_small_city(building_specs, width: int = 50, height: int = 24,
                         seed: int = None) -> City:
    """Build a City by randomly placing each (name, floor_count) building
    from `building_specs` onto the street grid, retrying placement up to
    200 times per building to avoid overlaps, then carving it in."""
    rng = random.Random(seed)
    max_floors = max(floors for _, floors in building_specs)
    city = City(width, height, max_floors)

    placed = []
    for name, floors in building_specs:
        for _ in range(200):
            w, h = rng.randint(5, 9), rng.randint(4, 7)
            x0, y0 = rng.randint(1, width - w - 1), rng.randint(1, height - h - 1)
            footprint = (x0, y0, x0 + w, y0 + h)
            if all(not _overlaps(footprint, p, margin=2) for p in placed):
                placed.append(footprint)
                _carve_building(city, name, *footprint, floors, rng)
                break
        else:
            raise RuntimeError(
                f"couldn't place building '{name}' -- try a bigger map or fewer buildings"
            )
    return city
