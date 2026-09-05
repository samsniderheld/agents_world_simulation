"""get_provider() is the whole modularity story for the Visuals tab: it
picks a Provider implementation based on visuals/data/config.yaml's
`provider` key. jobs.py and routes.py only ever talk to the Provider
interface (base.py) -- adding a "local" entry here (backed by a new
local.py implementing the same two methods) is the entire story for
switching to a local model server later.
"""

from .. import config


def get_provider():
    if config.PROVIDER == "fal":
        from .fal import FalProvider
        return FalProvider()
    raise ValueError(f"unknown visuals provider: {config.PROVIDER!r}")
