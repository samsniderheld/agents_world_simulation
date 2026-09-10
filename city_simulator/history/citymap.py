"""An ASCII map of every generated Place, drawn over a procedurally
generated archipelago -- not real coastline data, since this whole project
is about generating things, not tracing them. The geography is grown from
a domain-warped fractal noise field with only a soft center bias (see
_generate_island_mask): one main landmass surrounded by a scatter of
smaller organic islands, different every run, rasterized as Unicode
braille dot-density for a much finer, more organic look than a
block-character grid can give. Era neighborhoods are labeled
directly on the land, the way a hand-drawn map would, and in the web
viewer each one's row-band is colored separately -- carving up every
landmass into its actual neighborhoods rather than leaving it one flat
color -- along boundaries that are themselves noise-wobbled curves rather
than straight cuts (see _wavy_boundaries / build_map).

Deliberately split the labor: Python generates the shape and draws every
dot and label, so it's always well-formed regardless of how many places
exist. The LLM's only job is the creative part it's actually good at --
naming each era's cluster as a neighborhood and writing a one-line
caption -- with a plain grammar fallback if Ollama is unreachable.
"""

import colorsys
import math
import random

from . import config
from . import llm
from .eras import ERAS

# All of these are tunable knobs in config.yaml (see history/config.py) --
# aliased to module-level names here so the rest of this file reads exactly
# as it would with hardcoded constants.
CHAR_WIDTH = config.CHAR_WIDTH
CHAR_HEIGHT = config.CHAR_HEIGHT
DOT_W = CHAR_WIDTH * 2
DOT_H = CHAR_HEIGHT * 4

LAND_DENSITY = config.LAND_DENSITY     # fraction of land sub-dots actually drawn, for texture
WATER_DENSITY = config.WATER_DENSITY   # fraction of water sub-dots drawn, so the sea isn't a void

NOISE_SCALE = config.NOISE_SCALE             # smaller = broader, smoother terrain features
NOISE_OCTAVES = config.NOISE_OCTAVES
NOISE_PERSISTENCE = config.NOISE_PERSISTENCE
FALLOFF_POWER = config.FALLOFF_POWER         # exponent on the radial center bias
SEA_LEVEL = config.SEA_LEVEL                 # higher = less land, lower = more
CENTER_BIAS = config.CENTER_BIAS             # how strongly land clusters toward the map center
WARP_STRENGTH = config.WARP_STRENGTH         # domain-warp amplitude, in dots -- bends coastlines
MIN_ISLAND_DOTS = config.MIN_ISLAND_DOTS     # islets smaller than this get culled as specks
MAIN_ISLAND_MIN_FRACTION = config.MAIN_ISLAND_MIN_FRACTION  # main landmass floor, as a map fraction
EDGE_LANDMASS_CHANCE = config.EDGE_LANDMASS_CHANCE       # odds a run gets an off-frame side landmass
EDGE_LANDMASS_STRENGTH = config.EDGE_LANDMASS_STRENGTH   # its elevation boost at full strength

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

NEIGHBORHOOD_COLUMNS = config.NEIGHBORHOOD_COLUMNS
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


def _connected_components(mask: list) -> list:
    """4-connected land components of the mask, each a list of (row, col)
    dots -- how the archipelago post-processing below tells the main
    landmass from islets from single-dot noise specks."""
    seen = [[False] * DOT_W for _ in range(DOT_H)]
    components = []
    for r in range(DOT_H):
        for c in range(DOT_W):
            if not mask[r][c] or seen[r][c]:
                continue
            stack = [(r, c)]
            seen[r][c] = True
            component = []
            while stack:
                rr, cc = stack.pop()
                component.append((rr, cc))
                for nr, nc in ((rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1)):
                    if 0 <= nr < DOT_H and 0 <= nc < DOT_W and mask[nr][nc] and not seen[nr][nc]:
                        seen[nr][nc] = True
                        stack.append((nr, nc))
            components.append(component)
    return components


def _edge_landmass_boost(rng: random.Random):
    """An elevation-boost function for the off-frame secondary landmass
    (see _generate_island_mask's docstring), or None for runs that don't
    get one. Elliptical falloff from a center placed beyond the west or
    east map edge -- so the boosted ground always reads as continuing off
    camera -- reaching zero well before mid-map, which keeps a channel of
    open water between it and the main landmass most of the time (the
    occasional noise-drawn isthmus connecting them is a feature, not a
    bug)."""
    if rng.random() >= EDGE_LANDMASS_CHANCE:
        return None
    # Deliberately narrow and hugging the frame edge -- widening this
    # ellipse (or weakening the strength to compensate) makes the boost
    # reach far enough inland that the mass fuses with the main island in
    # a quarter of runs instead of reading as separate ground across the
    # water (measured over 30 seeds when tuning these ranges).
    a = DOT_W * rng.uniform(0.10, 0.16)
    b = DOT_H * rng.uniform(0.35, 0.60)
    ecx = -a * 0.25 if rng.random() < 0.5 else DOT_W + a * 0.25
    ecy = rng.uniform(0.25, 0.75) * DOT_H

    def boost(r: int, c: int) -> float:
        dx, dy = (c - ecx) / a, (r - ecy) / b
        d = math.sqrt(dx * dx + dy * dy)
        return EDGE_LANDMASS_STRENGTH * max(0.0, 1.0 - d)

    return boost


def _generate_island_mask(rng: random.Random) -> list:
    """True/False per (dot) row/col -- land or water, as an organic
    noise-grown archipelago rather than a templated shape.

    The old version thresholded noise against a hard Manhattan-proportioned
    elliptical envelope (so every map was the same almond silhouette) and
    then stamped 1-3 more ellipses offshore as satellite islands. This one
    lets the noise field itself decide the geography: a domain-warped
    fractal elevation field (warping the sample coordinates through a
    second noise field is what bends coastlines into real hooks, spits,
    and lagoons instead of blobby contour lines) minus only a soft radial
    center bias -- strong enough that land still clusters toward the
    middle of the map and fades out toward the edges, weak enough that the
    silhouette is different every run. Thresholding that at sea level
    naturally yields one big mass plus a scatter of smaller offshore
    islands of all sizes.

    Two guarantees the raw threshold can't make on its own, handled by
    connected-component post-processing: the largest landmass must be big
    enough to carry the city (the sea level auto-adjusts down until it
    is -- and back up if land swallows the whole map), and single-dot
    noise specks too small to read as islands get culled.

    On top of that, most runs (EDGE_LANDMASS_CHANCE) also get a secondary
    landmass hugging the west or east edge and running off-frame -- the
    way Brooklyn or New Jersey sits on a Manhattan-centered map: an
    elliptical elevation boost whose center lies beyond the map edge, so
    the mass visibly continues past the frame. The noise still draws its
    actual coastline; the boost only guarantees there's ground there."""
    noise = _make_perlin(rng)
    warp_noise = _make_perlin(rng)
    cx, cy = DOT_W / 2, DOT_H / 2
    warp_scale = NOISE_SCALE * 0.5
    edge_boost = _edge_landmass_boost(rng)

    elevation = [[0.0] * DOT_W for _ in range(DOT_H)]
    for r in range(DOT_H):
        for c in range(DOT_W):
            wx = c + WARP_STRENGTH * _fractal_noise(warp_noise, c * warp_scale, r * warp_scale, 2, 0.5)
            wy = r + WARP_STRENGTH * _fractal_noise(warp_noise, c * warp_scale + 91.7, r * warp_scale + 43.3, 2, 0.5)
            e = (_fractal_noise(noise, wx * NOISE_SCALE, wy * NOISE_SCALE, NOISE_OCTAVES, NOISE_PERSISTENCE) + 1) / 2
            dx, dy = (c - cx) / (DOT_W / 2), (r - cy) / (DOT_H / 2)
            distance = math.sqrt(dx * dx + dy * dy)
            elevation[r][c] = e - CENTER_BIAS * (distance ** FALLOFF_POWER)
            if edge_boost:
                elevation[r][c] += edge_boost(r, c)

    total = DOT_W * DOT_H
    sea = SEA_LEVEL
    mask = None
    for _ in range(12):
        mask = [[elevation[r][c] > sea for c in range(DOT_W)] for r in range(DOT_H)]
        components = _connected_components(mask)
        land = sum(len(comp) for comp in components)
        largest = max((len(comp) for comp in components), default=0)
        if largest < MAIN_ISLAND_MIN_FRACTION * total:
            sea -= 0.04   # too little (or too fragmented) land: drop the sea
        elif land > 0.55 * total:
            sea += 0.04   # wall-to-wall land: raise it back
        else:
            break

    final = [[False] * DOT_W for _ in range(DOT_H)]
    for component in _connected_components(mask):
        if len(component) >= MIN_ISLAND_DOTS:
            for r, c in component:
                final[r][c] = True
    return final


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


def _wavy_boundaries(noise, nominal: list, length: int, amplitude: float,
                      frequency: float, salt: float, min_gap: int, limit: int) -> list:
    """The organic replacement for straight band edges: one curve per
    nominal boundary position, each `length` samples long (one per dot
    column for the horizontal era boundaries, one per dot row for the
    vertical column split), wobbled by fractal noise. Clamped
    sample-by-sample so curves stay ordered and never cross each other or
    the map edge -- a neighborhood can get pinched thin somewhere, but
    never inverted away entirely."""
    curves = []
    for k, base in enumerate(nominal):
        curve = []
        for t in range(length):
            n = _fractal_noise(noise, t * frequency + salt, k * 19.37 + salt * 3.1, 2, 0.5)
            curve.append(base + n * amplitude)
        curves.append(curve)
    for t in range(length):
        prev = 0
        for k in range(len(curves)):
            v = int(round(curves[k][t]))
            v = max(v, prev + min_gap)
            v = min(v, limit - min_gap * (len(curves) - k))
            curves[k][t] = v
            prev = v
    return curves


def _dot_era_index(r: int, c: int, era_bounds: list) -> int:
    """Which era band (0 = northernmost/newest) the dot at (r, c) falls
    in, given the wavy per-column boundary curves."""
    b = 0
    while b < len(era_bounds) and r >= era_bounds[b][c]:
        b += 1
    return b


def _dot_col_index(r: int, c: int, col_bounds: list) -> int:
    """Which west-east column the dot at (r, c) falls in, given the wavy
    per-row boundary curves."""
    j = 0
    while j < len(col_bounds) and c >= col_bounds[j][r]:
        j += 1
    return j


def _find_spot(cells: list, width: int, claimed: set, rng: random.Random):
    """A free horizontal run of `width` characters starting on one of this
    neighborhood's own land cells. Falls back to the least-bad candidate
    if nothing is perfectly free, so a crowded section never just silently
    drops a place."""
    candidates = [(r, c) for (r, c) in cells if c + width <= CHAR_WIDTH]
    rng.shuffle(candidates)
    for r, c in candidates:
        run = [(r, c + i) for i in range(width)]
        if not any(cell in claimed for cell in run):
            claimed.update(run)
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


def build_map(places: list, figures: list, seed=None, llm_map: bool = False) -> dict:
    """`places`/`figures` are the entities.Place/Figure objects generate.py
    holds in memory -- call this before (or after) serializing to JSON.

    `llm_map=True` asks the LLM to draw the whole map itself as freeform
    ASCII art (see _try_llm_map) instead of the procedural noise-generated
    island -- validated (every place's numbered label must actually appear)
    and retried a couple of times before silently falling back to the
    procedural map, the same graceful-degradation shape as every other
    LLM-fill path in this project. An LLM-drawn map has no per-cell era
    coloring (that needs the exact structural grid alignment only the
    procedural path produces) -- see "mode" in the return value below.

    Returns {"text": <the plain multi-line map + legend + caption, for
    map.txt/console>, "body": <just the map art, no legend/caption -- what
    the web viewer displays>, "mode": "procedural" | "llm", "rows"/
    "cell_neighborhoods"/"palette"/"header_lines"/"row_prefix"/
    "border_line": <procedural-only, all empty in "llm" mode -- the exact
    per-cell grid data the web viewer uses to render era coloring>,
    "neighborhoods": <era id/column/name/color per grid cell, in map
    order, oldest to newest then west to east -- empty in "llm" mode>,
    "caption": <the caption line>}."""
    if llm_map:
        result = _try_llm_map(places, figures, seed)
        if result is not None:
            return result
    return _build_procedural_map(places, figures, seed)


def _build_procedural_map(places: list, figures: list, seed=None) -> dict:
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

    # Organic neighborhood boundaries: the era bands and the west/east
    # split are noise-wobbled curves (at dot resolution), not straight
    # cuts. Same overall structure -- oldest era southernmost, newest
    # northernmost, columns west to east -- just with borders that meander
    # the way real neighborhood lines do.
    boundary_noise = _make_perlin(rng)
    band_h = CHAR_HEIGHT // len(ERAS)
    era_bounds = _wavy_boundaries(
        boundary_noise,
        nominal=[(k + 1) * band_h * 4 for k in range(len(ERAS) - 1)],
        length=DOT_W, amplitude=7.0, frequency=0.055, salt=0.0,
        min_gap=4, limit=DOT_H,
    )
    col_bounds = _wavy_boundaries(
        boundary_noise,
        nominal=[end * 2 for (_start, end) in COLUMN_RANGES[:-1]],
        length=DOT_H, amplitude=9.0, frequency=0.05, salt=53.7,
        min_gap=4, limit=DOT_W,
    )
    band_eras = [era.id for era in reversed(ERAS)]  # top band = newest era

    # Char-cell era/column membership, sampled at each cell's center dot,
    # plus each (era x column) section's land cells -- what label
    # placement, centroids, and the exported cell_neighborhoods all key
    # off now that sections aren't rectangles anymore.
    char_era = [[None] * CHAR_WIDTH for _ in range(CHAR_HEIGHT)]
    char_col = [[0] * CHAR_WIDTH for _ in range(CHAR_HEIGHT)]
    cell_neighborhoods = [[None] * CHAR_WIDTH for _ in range(CHAR_HEIGHT)]
    section_land_cells = {}  # (era_id, column_index) -> [(row, col), ...]
    for cr in range(CHAR_HEIGHT):
        for cc in range(CHAR_WIDTH):
            era_id = band_eras[_dot_era_index(cr * 4 + 2, cc * 2 + 1, era_bounds)]
            ci = _dot_col_index(cr * 4 + 2, cc * 2 + 1, col_bounds)
            char_era[cr][cc] = era_id
            char_col[cr][cc] = ci
            if char_is_land[cr][cc]:
                cell_neighborhoods[cr][cc] = f"{era_id}_{ci}"
                section_land_cells.setdefault((era_id, ci), []).append((cr, cc))

    claimed = set()

    neighborhood_ids = [f"{era.id}_{ci}" for era in ERAS for ci in range(NEIGHBORHOOD_COLUMNS)]
    palette_colors = _neighborhood_palette(len(neighborhood_ids), start_hue=rng.random())
    neighborhood_colors = dict(zip(neighborhood_ids, palette_colors))

    legend = []              # (number, place) in display order
    used_names = set()       # lowercased, for case-insensitive dedup checks
    neighborhood_order = []  # properly-cased, oldest-to-newest, for the caption prompt
    neighborhoods_meta = []  # era_id/column/name/color, same order, for a map legend
    markers = []             # numbered place-label positions, char coords, for the canvas view
    number = 1

    for era_index, era in enumerate(ERAS):
        places_here = places_by_era[era.id][:]
        rng.shuffle(places_here)
        # Split this era's places roughly evenly across its columns -- there's
        # no real east/west fact about a place to key this off of, so an even
        # random split is exactly as meaningful as any other assignment would
        # be here, same spirit as the rest of this generator's randomness.
        column_groups = [places_here[ci::NEIGHBORHOOD_COLUMNS] for ci in range(NEIGHBORHOOD_COLUMNS)]

        for col_index_ in range(NEIGHBORHOOD_COLUMNS):
            neighborhood_id = f"{era.id}_{col_index_}"
            column_label = _COLUMN_LABELS[col_index_]
            places_section = column_groups[col_index_]
            section_land = section_land_cells.get((era.id, col_index_), [])

            neighborhood = _neighborhood_name(era, column_label, places_section, used_names, rng)
            used_names.add(neighborhood.lower())
            neighborhood_order.append(neighborhood)
            # Land-cell centroid of this section -- where the canvas view
            # centers the neighborhood's name. None when the section is
            # open water (the canvas just skips the label).
            centroid = None
            if section_land:
                centroid = {
                    "row": sum(r for r, _ in section_land) / len(section_land),
                    "col": sum(c for _, c in section_land) / len(section_land),
                }
            neighborhoods_meta.append({
                "id": neighborhood_id, "era_id": era.id, "column": column_label,
                "name": neighborhood, "color": neighborhood_colors[neighborhood_id],
                "place_ids": [p.id for p in places_section],
                "centroid": centroid,
            })
            spot = _find_spot(section_land, len(neighborhood) + 2, claimed, rng)
            if spot:
                _stamp(rows, spot[0], spot[1], neighborhood)

            for place in places_section:
                label = f"[{number}]"
                spot = _find_spot(section_land, len(label), claimed, rng)
                if spot:
                    _stamp(rows, spot[0], spot[1], label)
                    markers.append({
                        "number": number, "place_id": place.id,
                        "row": spot[0], "col": spot[1],
                    })
                legend.append((number, place))
                number += 1

    # river_header = " " * 8 + "HUDSON RIVER".ljust(CHAR_WIDTH // 2) + "EAST RIVER"
    grid_lines = ["".join(r) for r in rows]
    # out = [river_header, "  N", "  ^"]
    out = []
    for line in grid_lines:
        out.append("  |" + line)
    out.append("  +" + "-" * CHAR_WIDTH + ">")
    out.append("")
    # out.append("Legend:")
    # for number, place in legend:
    #     status_note = "" if place.status == "active" else f", {place.status} {place.closed_year}"
    #     out.append(f"  {number:>2}. {place.name} ({place.place_type}, founded {place.founded_year}{status_note})")

    # out.append("")
    # caption = _caption(neighborhood_order)
    # out.append(caption)

    palette = dict(neighborhood_colors)
    palette["water"] = WATER_COLOR
    palette["default"] = DEFAULT_NEIGHBORHOOD_COLOR

    return {
        "text": "\n".join(out),
        "body": "\n".join(out[:out.index("")]),
        "mode": "procedural",
        "rows": grid_lines,
        "cell_neighborhoods": cell_neighborhoods,
        "palette": palette,
        "neighborhoods": neighborhoods_meta,
        "row_prefix": "  |",
        "border_line": "  +" + "-" * CHAR_WIDTH + ">",
        # Everything the web viewer's interactive canvas rendering needs,
        # at full dot resolution -- the raw land/water mask (as "0"/"1"
        # strings, one per dot row, to keep the JSON compact), the wavy
        # era/column boundary curves that turn any land dot into its
        # neighborhood id (band_eras is the era per horizontal band, top
        # to bottom; era_boundaries[k][dot_col] is where band k ends;
        # column_boundaries[j][dot_row] is where column j ends), plus
        # where every [N] place label landed. The braille "rows" above are
        # this same data already rasterized down to text; the canvas draws
        # from the source instead.
        "graphic": {
            "dot_width": DOT_W, "dot_height": DOT_H,
            "char_width": CHAR_WIDTH, "char_height": CHAR_HEIGHT,
            "land": ["".join("1" if v else "0" for v in row) for row in mask],
            "band_eras": band_eras,
            "era_boundaries": era_bounds,
            "column_boundaries": col_bounds,
            "markers": markers,
        },
    }


def _try_llm_map(places: list, figures: list, seed=None) -> dict:
    """The whole-map alternative to _build_procedural_map: instead of a
    noise-generated island with Python-placed labels, the LLM draws the
    entire ASCII map itself -- freeform, including where it puts every
    place's [N] label. That freedom costs the per-cell era coloring the
    procedural path gives (see "mode" in the returned dict), so this is
    strictly opt-in (build_map's llm_map=True).

    Legend numbers are assigned up front, same era-then-shuffle order as
    the procedural path, so both modes produce the same legend for the
    same seed. Returns None (falls back to the procedural map) if the LLM
    is unreachable/disabled, or every retry attempt comes back malformed."""
    if not (config.LLM_FILL_NAMES and llm.available()):
        return None

    rng = random.Random(seed)
    figure_era = {f.id: f.era_id for f in figures}
    places_by_era = {era.id: [] for era in ERAS}
    for place in places:
        era_id = figure_era.get(place.founding_figure_id)
        if era_id in places_by_era:
            places_by_era[era_id].append(place)

    legend = []  # (number, place), era order then shuffled within era
    era_lines = []
    number = 1
    for era in ERAS:
        places_here = places_by_era[era.id][:]
        rng.shuffle(places_here)
        entries = []
        for place in places_here:
            entries.append(f"[{number}] {place.name} ({place.place_type})")
            legend.append((number, place))
            number += 1
        if entries:
            era_lines.append(f"{era.name} ({era.start_year}-{era.end_year}): " + "; ".join(entries))

    if not legend:
        return None

    places_block = "\n".join(era_lines)
    feedback = None
    body = None
    caption = None

    for _attempt in range(config.LLM_MAP_MAX_RETRIES + 1):
        try:
            raw = _generate_llm_map(places_block, feedback)
        except Exception:
            raw = None
        if not raw:
            feedback = "You did not reply with anything usable. Try again."
            continue

        parts = raw.rsplit("---", 1)
        candidate_body = parts[0].strip("\n")
        candidate_caption = parts[1].strip().strip('"') if len(parts) == 2 else ""

        problems = []
        lines = [l for l in candidate_body.split("\n") if l.strip()]
        if not (8 <= len(lines) <= 80):
            problems.append(f"the map had {len(lines)} non-blank lines, expected roughly 20-40")
        missing = [n for n, _ in legend if f"[{n}]" not in candidate_body]
        if missing:
            problems.append(
                f"these place labels were missing from the map: {', '.join(f'[{n}]' for n in missing)}"
            )
        if not candidate_caption:
            problems.append("there was no caption sentence after the '---' delimiter line")

        if not problems:
            body, caption = candidate_body, candidate_caption
            break
        feedback = "Your last attempt had problems: " + "; ".join(problems) + "."

    if body is None:
        return None

    out = [body, "", "Legend:"]
    for number, place in legend:
        status_note = "" if place.status == "active" else f", {place.status} {place.closed_year}"
        out.append(f"  {number:>2}. {place.name} ({place.place_type}, founded {place.founded_year}{status_note})")
    out.append("")
    out.append(caption)

    return {
        "text": "\n".join(out),
        "body": body,
        "mode": "llm",
        "rows": [],
        "cell_neighborhoods": [],
        "palette": {},
        "neighborhoods": [],
        "caption": caption,
        "header_lines": [],
        "row_prefix": "",
        "border_line": "",
    }


def _generate_llm_map(places_block: str, feedback: str = None) -> str:
    retry_note = f"\n\n{feedback} Please redraw the whole map, correcting this." if feedback else ""
    prompt = (
        "Draw a hand-drawn-style ASCII map of an east coast style "
        "City, as it might appear in an old atlas. Use simple characters "
        "for coastline, land, water, and streets (e.g. ~ for water, . or "
        "blank for open land, - | + for streets/blocks). Roughly 60-70 "
        "characters wide and 20-40 lines tall. Label the Hudson River on "
        "the west side and the East River on the east side somewhere on "
        "the map. Give a few neighborhoods evocative hand-lettered-looking "
        "names directly on the land.\n\n"
        "Every one of these places MUST appear on the map as its exact "
        "bracketed number label (e.g. [3]), placed somewhere sensible for "
        "its era (oldest era places further downtown/south, newer eras "
        "further uptown/north):\n\n"
        f"{places_block}\n\n"
        "After the map, write a line containing only --- and then, on the "
        "next line, one atmospheric caption sentence (max 20 words) for "
        "the whole map."
        f"{retry_note}\n\n"
        "Reply with ONLY the map, the --- line, and the caption -- no "
        "other commentary."
    )
    return llm.complete(
        prompt, temperature=0.85,
        context_tokens=config.LLM_MAP_CONTEXT_TOKENS,
        timeout=config.LLM_MAP_TIMEOUT_SECONDS,
    ).strip()
