"""An ASCII map of every generated Place, clustered by era along a
south-to-north axis -- mirroring how Manhattan actually grew over this
exact timeline: oldest settlement at the Battery (bottom), newest
expansion uptown (top). Each era's band is also drawn at a different
width, giving the whole image a rough island silhouette (narrow at the
Battery, bulging through the middle, narrowing again uptown) with the
Hudson and East Rivers filling the margins, and a handful of real bridges
crossing them once they'd actually have been built.

Deliberately split the labor: Python computes every coordinate -- island
width, water fill, marker positions, bridge placement -- and draws the
grid, so it's always perfectly aligned regardless of how many places
exist. The LLM's only job is the creative part it's actually good at --
naming each era's cluster as a neighborhood and writing a one-line
caption -- with a plain grammar fallback if Ollama is unreachable.
"""

import math
import random

import config
import llm
from eras import ERAS

# How many marker-columns wide each era's band is, oldest (index 0, the
# Battery) to newest (uptown) -- this is what gives the map its island
# shape. MAX_COLS is derived from it so every band keeps at least a couple
# of columns of water on each side, even at the widest point.
ISLAND_COLS_PROFILE = [4, 6, 8, 10, 10, 8, 6, 5]
MAX_COLS = max(ISLAND_COLS_PROFILE) + 4
MIN_ROWS_PER_ERA = 3
WATER_CHAR = "~"

# (name, year actually built, era-band index it crosses at, which shore).
# Only drawn once the map's final year has reached that bridge's real
# opening year, via _bridges_for_era().
BRIDGES = [
    ("Brooklyn Bridge", 1883, 0, "east"),
    ("Williamsburg Bridge", 1903, 1, "east"),
    ("Manhattan Bridge", 1909, 1, "east"),
    ("Queensboro Bridge", 1909, 4, "east"),
    ("Triborough Bridge", 1936, 6, "east"),
    ("George Washington Bridge", 1931, 7, "west"),
]


def _cell_width(num_places: int) -> int:
    digits = len(str(max(num_places, 1)))
    return digits + 3  # "[" + digits + "]" + 1 trailing space


def _neighborhood_name(era, places_here: list, used_names: set, rng: random.Random) -> str:
    # The era name itself already makes this unique across eras, unlike an
    # LLM answer -- so it's the fallback both when the model's unavailable
    # and when it ignores the exclusion list below (e.g. "Lower East Side"
    # is such an obvious answer for several different tenement-heavy eras
    # that a plain "don't repeat yourself" instruction doesn't always hold).
    fallback = f"{era.name.split('(')[0].strip()} Quarter"
    if not (config.LLM_FILL_NAMES and llm.available()):
        return fallback
    try:
        sample = ", ".join(f"{p.name} ({p.place_type})" for p in places_here[:6]) or "a few scattered lots"
        exclusion = (
            f" Do not use any of these names, already used for other eras on this "
            f"map: {', '.join(sorted(used_names))}."
            if used_names else ""
        )
        prompt = (
            "In one short, evocative neighborhood name (2-4 words, no punctuation, "
            f"no quotes), create a new name for a neighborhood for an alternate history NYC during the \"{era.name}\" era "
            f"({era.start_year}-{era.end_year}) that's home to: {sample}.{exclusion} "
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


def _bridges_for_era_index(era_index: int, max_year: int):
    return [b for b in BRIDGES if b[2] == era_index and b[1] <= max_year]


def build_map(places: list, figures: list, seed=None) -> str:
    """`places`/`figures` are the entities.Place/Figure objects generate.py
    holds in memory -- call this before (or after) serializing to JSON."""
    rng = random.Random(seed)
    figure_era = {f.id: f.era_id for f in figures}
    max_year = max(era.end_year for era in ERAS)

    places_by_era = {era.id: [] for era in ERAS}
    for place in places:
        era_id = figure_era.get(place.founding_figure_id)
        if era_id in places_by_era:
            places_by_era[era_id].append(place)

    cell_width = _cell_width(len(places))
    total_width = MAX_COLS * cell_width

    legend = []       # (number, place) in display order
    band_blocks = []  # [row strings] per era, oldest era first
    used_names = set()        # lowercased, for case-insensitive dedup checks
    neighborhood_order = []   # properly-cased, oldest-to-newest, for the caption prompt
    number = 1

    for era_index, era in enumerate(ERAS):
        places_here = places_by_era[era.id]
        neighborhood = _neighborhood_name(era, places_here, used_names, rng)
        used_names.add(neighborhood.lower())
        neighborhood_order.append(neighborhood)

        island_cols = ISLAND_COLS_PROFILE[era_index]
        water_cols_each_side = (MAX_COLS - island_cols) // 2
        land_start = water_cols_each_side * cell_width
        land_end = land_start + island_cols * cell_width

        bridges_here = _bridges_for_era_index(era_index, max_year)
        rows_needed = max(
            MIN_ROWS_PER_ERA,
            math.ceil(len(places_here) / island_cols) if places_here else 0,
            len(bridges_here),
        ) or MIN_ROWS_PER_ERA

        # Water everywhere, land (blank, ready for markers) only inside
        # this band's island width -- this is what produces the silhouette.
        rows = [[WATER_CHAR] * total_width for _ in range(rows_needed)]
        for row in rows:
            for x in range(land_start, land_end):
                row[x] = " "

        slots = [(r, c) for r in range(rows_needed) for c in range(island_cols)]
        rng.shuffle(slots)
        for place, (r, c) in zip(places_here, slots):
            label = f"[{number}]"
            x = land_start + c * cell_width
            for i, ch in enumerate(label):
                if x + i < land_end:
                    rows[r][x + i] = ch
            legend.append((number, place))
            number += 1

        # One label per row: the neighborhood name on row 0, plus any
        # bridge crossing this band, each on its own row so labels never
        # collide.
        row_labels = {0: [neighborhood]}
        for i, (bname, byear, _idx, side) in enumerate(bridges_here):
            r = i % rows_needed
            if side == "east":
                for x in range(land_end, total_width):
                    rows[r][x] = "="
            else:
                for x in range(0, land_start):
                    rows[r][x] = "="
            row_labels.setdefault(r, []).append(f"{bname} ({byear})")

        row_strings = []
        for r, row in enumerate(rows):
            line = "".join(row)
            labels = row_labels.get(r)
            if labels:
                line += "    " + " / ".join(labels)
            row_strings.append(line)
        band_blocks.append(row_strings)

    band_blocks.reverse()  # newest era at the top of the map

    # 8-space lead-in matches the "     |  " prefix every grid row below
    # gets, so these two labels sit directly above their actual water columns.
    river_header = " " * 8 + "HUDSON RIVER".ljust(total_width // 2) + "EAST RIVER"
    out = [river_header, "     N", "     ^"]
    for row_strings in band_blocks:
        for r in row_strings:
            out.append(f"     |  {r}")
        out.append("     |")
    out.append("     +" + "-" * (total_width + 4) + ">")
    out.append("")
    out.append("Legend:")
    for number, place in legend:
        status_note = "" if place.status == "active" else f", {place.status} {place.closed_year}"
        out.append(f"  {number:>2}. {place.name} ({place.place_type}, founded {place.founded_year}{status_note})")

    out.append("")
    out.append(_caption(neighborhood_order))

    return "\n".join(out)
