"""The eras the generated history is segmented into (see plan: analogous to
each Caves of Qud Sultan's reign) -- the current theme's `eras` (theme.py).
Each era spawns config.FIGURES_PER_ERA new Figures whose event chains run
within that era's years, but whose events can act on Places founded in any
earlier era -- see generate.py.
"""

from dataclasses import dataclass

import theme


@dataclass(frozen=True)
class Era:
    id: str
    name: str
    start_year: int
    end_year: int
    description: str


def all_eras() -> list:
    t = theme.current()
    return t.memo("eras", lambda: [Era(**e) for e in t["eras"]])


def eras_by_id() -> dict:
    t = theme.current()
    return t.memo("eras_by_id", lambda: {era.id: era for era in all_eras()})


def era_for_year(year: int) -> Era:
    """The era a given year falls in. A year in a gap between eras (1917-20)
    belongs to the one before it; one past the last era, to the last."""
    eras = all_eras()
    return next((era for era in reversed(eras) if era.start_year <= year), eras[0])
