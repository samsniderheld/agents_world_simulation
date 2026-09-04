"""The eras the generated history is segmented into (see plan: analogous to
each Caves of Qud Sultan's reign) -- loaded from eras.yaml. Each era spawns
config.FIGURES_PER_ERA new Figures whose event chains run within that era's
years, but whose events can act on Places founded in any earlier era -- see
generate.py.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

_YAML_PATH = Path(__file__).parent / "data" / "eras.yaml"

with open(_YAML_PATH) as _f:
    _RAW = yaml.safe_load(_f)


@dataclass(frozen=True)
class Era:
    id: str
    name: str
    start_year: int
    end_year: int
    description: str


ERAS = [Era(**e) for e in _RAW["eras"]]
ERAS_BY_ID = {era.id: era for era in ERAS}
