"""get_provider() is the whole modularity story for the Visuals tab: it
picks a Provider implementation based on which name is active --
config.PROVIDER at startup (from config.yaml), or whatever routes.py's
POST /api/visuals/provider last switched it to. jobs.py and routes.py only
ever talk to the Provider interface (base.py) -- adding a "local" entry
here (backed by a new local.py implementing the same two methods) is the
entire story for switching to a local model server later.

Memoized per provider name, not just once: switching providers at runtime
(the Visuals tab's provider selector) shouldn't discard and recreate the
one already built for a name you switch back to -- for LocalProvider in
particular, that instance is what holds the loaded (multi-GB) pipeline in
memory, and reconstructing it would mean reloading the model.
"""

from .. import config

AVAILABLE_PROVIDERS = ["fal", "local"]

_instances = {}


def get_provider(name: str = None):
    name = name or config.PROVIDER
    if name in _instances:
        return _instances[name]

    if name == "fal":
        from .fal import FalProvider
        instance = FalProvider()
    elif name == "local":
        from .local import LocalProvider
        instance = LocalProvider()
    else:
        raise ValueError(f"unknown visuals provider: {name!r}")

    _instances[name] = instance
    return instance
