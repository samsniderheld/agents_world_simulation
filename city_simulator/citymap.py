"""An ASCII map of every generated Place, drawn over a procedurally
generated island -- not real coastline data, since this whole project is
about generating things, not tracing them. The island's silhouette comes
from Perlin noise thresholded against a Manhattan-proportioned envelope
(narrow at both the north and south tips, bulging through the middle), so
the coastline gets real bays and points instead of just a wobbly edge,
rasterized as Unicode braille dot-density for a much finer, more organic
look than a block-character grid can give. Era neighborhoods are labeled
directly on the land, the way a hand-drawn map would, and in the web
viewer each one's row-band is colored separately -- carving up every
landmass into its actual neighborhoods rather than leaving it one flat
color (see _char_neighborhood_grid / build_map).

Deliberately split the labor: Python generates the shape and draws every
dot and label, so it's always well-formed regardless of how many places
exist. The LLM's only job is the creative part it's actually good at --
naming each era's cluster as a neighborhood and writing a one-line
caption -- with a plain grammar fallback if Ollama is unreachable.
"""

import colorsys
import math
import random

import history_config as config
import history_llm as llm
from eras import ERAS

CHAR_WIDTH = 74
CHAR_HEIGHT = 44
DOT_W = CHAR_WIDTH * 2
DOT_H = CHAR_HEIGHT * 4

LAND_DENSITY = 0.62   # fraction of land sub-dots actually drawn, for texture
WATER_DENSITY = 0.10  # fraction of water sub-dots drawn, so the sea isn't a void

NOISE_SCALE = 0.05       # smaller = broader, smoother terrain features
NOISE_OCTAVES = 5
NOISE_PERSISTENCE = 0.5
FALLOFF_POWER = 2.2      # higher = sharper edge, lower = softer/larger island
SEA_LEVEL = -0.20        # higher = smaller/patchier landmass, lower = bigger/more solid
SATELLITE_SEA_LEVEL = -0.30  # more generous than SEA_LEVEL -- a small island
                             # needs a lower bar to read as solid rather than
                             # fragmenting away to nothing at its small size

_BRAILLE_BASE = 0x2800
_BRAILLE_BIT = {
    (0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
    (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80,
}

# Every era's row-band gets its own color, and each band is itself sliced
# into this many east-west columns -- these (era x column) cells ARE the
# neighborhoods (see _neighborhood_name / build_map), so coloring by them
# is what actually divides each landmass up into a real 2D grid of
# visually distinct sections, rather than one flat color or a single
# north-south strip. Generated rather than hand-picked so the palette
# always matches however many eras/columns exist; this only ever reaches
# the web viewer, since plain text can't carry color.
DEFAULT_NEIGHBORHOOD_COLOR = "#d4d4d4"  # land with no era/column mapped (shouldn't happen)
WATER_COLOR = "#3b5f7a"

NEIGHBORHOOD_COLUMNS = 2
_COLUMN_LABELS = ["West", "East"]  # sized to NEIGHBORHOOD_COLUMNS -- update together


def _column_ranges(n: int) -> list:
    """n roughly-equal character-column ranges spanning CHAR_WIDTH, west to
    east -- the vertical cuts that, combined with the era row-bands, carve
    the map into a real grid instead of just horizontal strips."""
    step = CHAR_WIDTH / n
    return [(round(i * step), round((i + 1) * step)) for i in range(n)]


COLUMN_RANGES = _column_ranges(NEIGHBORHOOD_COLUMNS)


_GOLDEN_RATIO_CONJUGATE = 0.618033988749895


def _neighborhood_palette(n: int, start_hue: float = 0.0) -> list:
    """n richly-saturated, well-separated colors. Hues step by the golden
    ratio's conjugate rather than a simple 1/n division -- list order is
    era-major/column-minor, which is also usually map-adjacent (the next
    column over, or the next era band up), so a plain linear hue sweep put
    neighbors only a few degrees apart on the color wheel and they read as
    near-identical. The golden-ratio step scatters consecutive entries far
    apart in hue instead, however many there are. Lower lightness/higher
    saturation than a pastel gives real contrast against the dark UI."""
    colors = []
    hue = start_hue % 1.0
    for _ in range(n):
        r, g, b = colorsys.hls_to_rgb(hue, 0.58, 0.75)
        colors.append("#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255)))
        hue = (hue + _GOLDEN_RATIO_CONJUGATE) % 1.0
    return colors


def _make_perlin(rng: random.Random):
    """A standard 2D gradient (Perlin) noise function, seeded from `rng` --
    no numpy/noise dependency, just the classic algorithm: a shuffled
    permutation table, smoothstep-interpolated between four corner
    gradients per cell. Returns noise(x, y) -> roughly [-1, 1]."""
    perm = list(range(256))
    rng.shuffle(perm)
    perm = perm * 2  # avoid index-wrapping checks below

    def fade(t):
        return t * t * t * (t * (t * 6 - 15) + 10)

    def lerp(t, a, b):
        return a + t * (b - a)

    def grad(hash_, x, y):
        # 4 gradient directions is the standard simplification for 2D
        # Perlin noise (Ken Perlin's own reference implementation does
        # the same trick for the 2D case).
        h = hash_ & 3
        u = x if h < 2 else y
        v = y if h < 2 else x
        return (u if h & 1 == 0 else -u) + (v if h & 2 == 0 else -v)

    def noise(x, y):
        xi, yi = int(math.floor(x)) & 255, int(math.floor(y)) & 255
        xf, yf = x - math.floor(x), y - math.floor(y)
        u, v = fade(xf), fade(yf)
        aa, ab = perm[perm[xi] + yi], perm[perm[xi] + yi + 1]
        ba, bb = perm[perm[xi + 1] + yi], perm[perm[xi + 1] + yi + 1]
        x1 = lerp(u, grad(aa, xf, yf), grad(ba, xf - 1, yf))
        x2 = lerp(u, grad(ab, xf, yf - 1), grad(bb, xf - 1, yf - 1))
        return lerp(v, x1, x2)

    return noise


def _fractal_noise(noise, x: float, y: float, octaves: int, persistence: float) -> float:
    """Layer several octaves of the base noise (each higher-frequency and
    lower-amplitude than the last) for the small-scale roughness real
    coastlines have on top of their broad curves, normalized to [-1, 1]."""
    total, amplitude, frequency, max_value = 0.0, 1.0, 1.0, 0.0
    for _ in range(octaves):
        total += noise(x * frequency, y * frequency) * amplitude
        max_value += amplitude
        amplitude *= persistence
        frequency *= 2.0
    return total / max_value


def _land_at(noise, col: float, row: float, cx: float, cy: float,
             a: float, b: float, sea_level: float) -> bool:
    """Shared land test: fractal noise minus an elliptical falloff from
    (cx, cy) with semi-axes (a, b), thresholded at sea_level. The main
    landmass and each satellite island (see _add_satellite_islands) are
    both just this same test centered somewhere different."""
    dx, dy = (col - cx) / a, (row - cy) / b
    distance = math.sqrt(dx * dx + dy * dy)
    n = _fractal_noise(noise, col * NOISE_SCALE, row * NOISE_SCALE, NOISE_OCTAVES, NOISE_PERSISTENCE)
    elevation = (n + 1) / 2  # normalize from [-1, 1] to [0, 1]
    return (elevation - distance ** FALLOFF_POWER) > sea_level


def _add_satellite_islands(mask: list, noise, rng: random.Random):
    """1-3 more landmasses near the main one -- the boroughs/New-Jersey
    character of the real NYC area, without tracing it: each is the same
    noise field, just thresholded around its own center point elsewhere.
    Sized anywhere from a small island up to comparable to the main
    landmass itself, and deliberately allowed to center off-grid, so a
    big one reads the way Brooklyn or New Jersey would on a map centered
    on Manhattan -- a landmass that just runs off the edge, not a tidy
    island fully contained in view."""
    cx, cy = DOT_W / 2, DOT_H / 2
    main_a, main_b = DOT_W * 0.30, DOT_H * 0.48
    placed = []  # (cx, cy, a, b) of every satellite placed so far

    count = rng.randint(1, 3)
    attempts = 0
    while len(placed) < count and attempts < 300:
        attempts += 1
        a, b = DOT_W * rng.uniform(0.08, 0.32), DOT_H * rng.uniform(0.07, 0.28)
        # Center can land up to half its own radius off-grid -- enough to
        # spill off an edge while still guaranteeing some of it is visible.
        col = rng.uniform(-0.5 * a, DOT_W + 0.5 * a)
        row = rng.uniform(-0.5 * b, DOT_H + 0.5 * b)

        dx, dy = (col - cx) / main_a, (row - cy) / main_b
        d_main = math.sqrt(dx * dx + dy * dy)
        # A bigger satellite needs proportionally more center-to-center
        # clearance to actually stay offshore -- a flat distance range
        # here let a big enough satellite overlap (and silently fuse
        # into) the main landmass instead of reading as a separate one
        # across the water, the way a real borough always is.
        satellite_radius_norm = ((a / main_a) + (b / main_b)) / 2
        min_d = 1.0 + satellite_radius_norm + 0.15
        if not (min_d < d_main < min_d + 1.0):
            continue
        if any(math.hypot(col - ocx, row - ocy) < max(a, b) + max(oa, ob)
               for ocx, ocy, oa, ob in placed):
            continue  # keep clear of satellites already placed
        placed.append((col, row, a, b))

    for icx, icy, a, b in placed:
        row_lo, row_hi = max(0, int(icy - b - 2)), min(DOT_H, int(icy + b + 2))
        col_lo, col_hi = max(0, int(icx - a - 2)), min(DOT_W, int(icx + a + 2))
        for row in range(row_lo, row_hi):
            for col in range(col_lo, col_hi):
                if _land_at(noise, col, row, icx, icy, a, b, SATELLITE_SEA_LEVEL):
                    mask[row][col] = True


def _generate_island_mask(rng: random.Random) -> list:
    """True/False per (dot) row/col -- land or water. This is the standard
    noise-terrain technique (see e.g. redblobgames' writeups on generating
    maps with noise): a full 2D fractal-noise height field, biased by an
    elongated elliptical falloff (tall north-south, narrow east-west, so
    the overall silhouette still reads as a Manhattan-like island rather
    than a circular blob), thresholded at a sea level. The landmass's
    actual shape -- not just its coastline -- is whatever that combination
    produces: real bays and points, plus 1-3 smaller satellite islands
    offshore (see _add_satellite_islands) for an archipelago rather than
    one lone landmass."""
    noise = _make_perlin(rng)
    mask = [[False] * DOT_W for _ in range(DOT_H)]
    cx, cy = DOT_W / 2, DOT_H / 2
    a, b = DOT_W * 0.30, DOT_H * 0.48  # ellipse semi-axes

    for row in range(DOT_H):
        for col in range(DOT_W):
            mask[row][col] = _land_at(noise, col, row, cx, cy, a, b, SEA_LEVEL)

    _add_satellite_islands(mask, noise, rng)
    return mask


def _dot_grid(mask: list, rng: random.Random) -> list:
    """Texture the solid mask into a sparser dot pattern -- land denser
    than water -- purely cosmetic, so terrain reads as dotted density
    rather than solid blocks."""
    grid = [[False] * DOT_W for _ in range(DOT_H)]
    for row in range(DOT_H):
        for col in range(DOT_W):
            density = LAND_DENSITY if mask[row][col] else WATER_DENSITY
            grid[row][col] = rng.random() < density
    return grid


def _to_braille_rows(dots: list) -> list:
    """Pack the DOT_W x DOT_H dot grid down into CHAR_WIDTH x CHAR_HEIGHT
    braille characters (each covers a 2-wide x 4-tall block of dots)."""
    rows = []
    for cr in range(CHAR_HEIGHT):
        line = []
        for cc in range(CHAR_WIDTH):
            code = _BRAILLE_BASE
            for dr in range(4):
                for dc in range(2):
                    if dots[cr * 4 + dr][cc * 2 + dc]:
                        code |= _BRAILLE_BIT[(dc, dr)]
            line.append(chr(code))
        rows.append(line)
    return rows


def _char_is_land(mask: list) -> list:
    """Character-cell land/water: land if any of its 2x4 sub-dots are land."""
    grid = [[False] * CHAR_WIDTH for _ in range(CHAR_HEIGHT)]
    for cr in range(CHAR_HEIGHT):
        for cc in range(CHAR_WIDTH):
            grid[cr][cc] = any(
                mask[cr * 4 + dr][cc * 2 + dc]
                for dr in range(4) for dc in range(2)
            )
    return grid


def _era_row_lookup() -> list:
    """Character row -> the era whose band that row falls in -- the same
    south-to-north bands _era_row_range already defines, just inverted
    into a per-row lookup so a character cell's neighborhood is a single
    array index instead of re-deriving the band on every cell."""
    lookup = [None] * CHAR_HEIGHT
    for era_index, era in enumerate(ERAS):
        start, end = _era_row_range(era_index)
        for r in range(start, min(end, CHAR_HEIGHT)):
            lookup[r] = era.id
    return lookup


def _column_index_lookup() -> list:
    """Character column -> which column-band it falls in (see
    COLUMN_RANGES), the west-east counterpart to _era_row_lookup."""
    lookup = [0] * CHAR_WIDTH
    for col_index, (start, end) in enumerate(COLUMN_RANGES):
        for c in range(start, min(end, CHAR_WIDTH)):
            lookup[c] = col_index
    return lookup


def _char_neighborhood_grid(char_is_land: list, row_era: list, col_index: list) -> list:
    """Character-cell neighborhood id ("{era_id}_{column}", None for
    water). This is what actually divides each landmass into a real grid
    of separately colored sections: a landmass spanning multiple eras'
    row-bands and multiple columns shows one color per (era, column) cell
    rather than one flat color or a single north-south strip."""
    grid = [[None] * CHAR_WIDTH for _ in range(CHAR_HEIGHT)]
    for cr in range(CHAR_HEIGHT):
        era_id = row_era[cr]
        for cc in range(CHAR_WIDTH):
            grid[cr][cc] = f"{era_id}_{col_index[cc]}" if char_is_land[cr][cc] else None
    return grid


def _era_row_range(era_index: int) -> tuple:
    """Character rows this era's band occupies -- era 0 (oldest) at the
    south/bottom, the newest era at the north/top."""
    band = CHAR_HEIGHT // len(ERAS)
    from_top = len(ERAS) - 1 - era_index
    start = from_top * band
    end = CHAR_HEIGHT if era_index == 0 else start + band
    return start, end


def _find_spot(start_row: int, end_row: int, start_col: int, end_col: int, width: int,
                char_is_land: list, claimed: set, rng: random.Random):
    """A free, on-land horizontal run of `width` characters within this
    neighborhood's row band AND column band. Falls back to the least-bad
    candidate if nothing is perfectly free, so a crowded section never
    just silently drops a place."""
    candidates = []
    max_c = min(end_col, CHAR_WIDTH) - width
    for r in range(start_row, min(end_row, CHAR_HEIGHT)):
        for c in range(start_col, max_c):
            if char_is_land[r][c]:
                candidates.append((r, c))
    rng.shuffle(candidates)
    for r, c in candidates:
        cells = [(r, c + i) for i in range(width)]
        if not any(cell in claimed for cell in cells):
            claimed.update(cells)
            return r, c
    if candidates:
        r, c = candidates[0]
        claimed.update((r, c + i) for i in range(width))
        return r, c
    return None


def _neighborhood_name(era, column_label: str, places_here: list, used_names: set, rng: random.Random) -> str:
    fallback = f"{column_label} {era.name.split('(')[0].strip()} Quarter"
    if not (config.LLM_FILL_NAMES and llm.available()):
        return fallback
    try:
        sample = ", ".join(f"{p.name} ({p.place_type})" for p in places_here[:6]) or "a few scattered lots"
        exclusion = (
            f" Do not use any of these names, already used for other neighborhoods on this "
            f"map: {', '.join(sorted(used_names))}."
            if used_names else ""
        )
        prompt = (
            "In one short, evocative neighborhood name (2-4 words, no punctuation, "
            f"no quotes), create a new name for a neighborhood for an alternate history NYC during the \"{era.name}\" era "
            f"({era.start_year}-{era.end_year}), specifically its {column_label.lower()} side, "
            f"that's home to: {sample}.{exclusion} "
            "Reply with ONLY the neighborhood name."
        )
        name = llm.complete(prompt, temperature=0.9).strip().strip('"').strip(".")
        if name and "\n" not in name and 2 <= len(name) <= 40 and name.lower() not in used_names:
            return name
    except Exception:
        pass
    return fallback


def _caption(neighborhood_names: list) -> str:
    fallback = "A city grown north from the harbor, one generation built atop the last."
    if not (config.LLM_FILL_NAMES and llm.available()):
        return fallback
    try:
        prompt = (
            "Write one atmospheric sentence (max 20 words) captioning an old "
            "hand-drawn map of New York City spanning these neighborhoods, oldest "
            f"to newest: {', '.join(neighborhood_names)}. Reply with ONLY the sentence."
        )
        caption = llm.complete(prompt, temperature=0.9).strip().strip('"')
        if caption and "\n" not in caption and len(caption) <= 220:
            return caption
    except Exception:
        pass
    return fallback


def _stamp(rows: list, row: int, col: int, text: str):
    for i, ch in enumerate(text):
        if 0 <= col + i < CHAR_WIDTH:
            rows[row][col + i] = ch


def build_map(places: list, figures: list, seed=None) -> dict:
    """`places`/`figures` are the entities.Place/Figure objects generate.py
    holds in memory -- call this before (or after) serializing to JSON.

    Returns {"text": <the plain multi-line map, for map.txt/console -- what
    this function used to return outright>, "rows": <the grid's CHAR_HEIGHT
    lines alone, no left-margin>, "cell_neighborhoods": <same-shaped grid of
    era id per character cell, None for water -- each era's row-band IS a
    neighborhood, so this is what divides every landmass into separately
    colored sections instead of tinting it one flat color>, "palette":
    <"{era_id}_{column}" -> hex color, plus "water"/"default">,
    "neighborhoods": <era id/column/name/color per grid cell, in map
    order, oldest to newest then west to east>, "caption": <the caption
    line>}. Only the web viewer (which can actually render color) uses
    anything past "text"."""
    rng = random.Random(seed)
    figure_era = {f.id: f.era_id for f in figures}

    places_by_era = {era.id: [] for era in ERAS}
    for place in places:
        era_id = figure_era.get(place.founding_figure_id)
        if era_id in places_by_era:
            places_by_era[era_id].append(place)

    mask = _generate_island_mask(rng)
    dots = _dot_grid(mask, rng)
    rows = _to_braille_rows(dots)
    char_is_land = _char_is_land(mask)
    row_era = _era_row_lookup()
    col_index = _column_index_lookup()
    cell_neighborhoods = _char_neighborhood_grid(char_is_land, row_era, col_index)
    claimed = set()

    neighborhood_ids = [f"{era.id}_{ci}" for era in ERAS for ci in range(NEIGHBORHOOD_COLUMNS)]
    palette_colors = _neighborhood_palette(len(neighborhood_ids), start_hue=rng.random())
    neighborhood_colors = dict(zip(neighborhood_ids, palette_colors))

    legend = []              # (number, place) in display order
    used_names = set()       # lowercased, for case-insensitive dedup checks
    neighborhood_order = []  # properly-cased, oldest-to-newest, for the caption prompt
    neighborhoods_meta = []  # era_id/column/name/color, same order, for a map legend
    number = 1

    for era_index, era in enumerate(ERAS):
        start_row, end_row = _era_row_range(era_index)
        places_here = places_by_era[era.id][:]
        rng.shuffle(places_here)
        # Split this era's places roughly evenly across its columns -- there's
        # no real east/west fact about a place to key this off of, so an even
        # random split is exactly as meaningful as any other assignment would
        # be here, same spirit as the rest of this generator's randomness.
        column_groups = [places_here[ci::NEIGHBORHOOD_COLUMNS] for ci in range(NEIGHBORHOOD_COLUMNS)]

        for col_index_, (start_col, end_col) in enumerate(COLUMN_RANGES):
            neighborhood_id = f"{era.id}_{col_index_}"
            column_label = _COLUMN_LABELS[col_index_]
            places_section = column_groups[col_index_]

            neighborhood = _neighborhood_name(era, column_label, places_section, used_names, rng)
            used_names.add(neighborhood.lower())
            neighborhood_order.append(neighborhood)
            neighborhoods_meta.append({
                "era_id": era.id, "column": column_label,
                "name": neighborhood, "color": neighborhood_colors[neighborhood_id],
            })
            spot = _find_spot(start_row, end_row, start_col, end_col, len(neighborhood) + 2,
                               char_is_land, claimed, rng)
            if spot:
                _stamp(rows, spot[0], spot[1], neighborhood)

            for place in places_section:
                label = f"[{number}]"
                spot = _find_spot(start_row, end_row, start_col, end_col, len(label),
                                   char_is_land, claimed, rng)
                if spot:
                    _stamp(rows, spot[0], spot[1], label)
                legend.append((number, place))
                number += 1

    river_header = " " * 8 + "HUDSON RIVER".ljust(CHAR_WIDTH // 2) + "EAST RIVER"
    grid_lines = ["".join(r) for r in rows]
    out = [river_header, "  N", "  ^"]
    for line in grid_lines:
        out.append("  |" + line)
    out.append("  +" + "-" * CHAR_WIDTH + ">")
    out.append("")
    out.append("Legend:")
    for number, place in legend:
        status_note = "" if place.status == "active" else f", {place.status} {place.closed_year}"
        out.append(f"  {number:>2}. {place.name} ({place.place_type}, founded {place.founded_year}{status_note})")

    out.append("")
    caption = _caption(neighborhood_order)
    out.append(caption)

    palette = dict(neighborhood_colors)
    palette["water"] = WATER_COLOR
    palette["default"] = DEFAULT_NEIGHBORHOOD_COLOR

    return {
        "text": "\n".join(out),
        "rows": grid_lines,
        "cell_neighborhoods": cell_neighborhoods,
        "palette": palette,
        "neighborhoods": neighborhoods_meta,
        "caption": caption,
        # so a colored (web-only) rendering of the grid doesn't have to
        # re-parse this framing back out of "text"
        "header_lines": [river_header, "  N", "  ^"],
        "row_prefix": "  |",
        "border_line": "  +" + "-" * CHAR_WIDTH + ">",
    }
