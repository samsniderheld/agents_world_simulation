"""get_provider() is the whole modularity story for visuals/: it
picks a Provider implementation based on which name is active --
config.PROVIDER at startup (from config.yaml), or whatever routes.py's
POST /api/visuals/provider last switched it to. jobs.py and routes.py only
ever talk to the Provider interface (base.py) -- adding a "local" entry
here (backed by a new local.py implementing the same two methods) is the
entire story for switching to a local model server later.

Memoized per provider name, not just once: switching providers at runtime
(POST /api/visuals/provider) shouldn't discard and recreate the
one already built for a name you switch back to -- for LocalProvider in
particular, that instance is what holds the loaded (multi-GB) pipeline in
memory, and reconstructing it would mean reloading the model.
"""

from .. import config

AVAILABLE_PROVIDERS = ["fal", "local", "comfyui"]

# What the node-based UI's canvas can honor per provider, so it can grey
# out a port/field instead of failing at generate time (per the design
# spec). Verified against each provider's actual implementation, not
# assumed: fal's image editing goes through Gemini 3 Pro Image Preview's
# edit model (image_paths -- see fal.py's generate_image); local's
# Z-Image Turbo pipeline (local.py) explicitly raises on image_paths
# (text-to-image only) and never implements video/music at all.
CAPABILITIES = {
    "fal": {
        "supports_reference_images": True,
        "supports_video": True,
        "supports_music": True,
    },
    "local": {
        "supports_reference_images": False,
        "supports_video": False,
        "supports_music": False,
    },
    # comfyui.py: images with any number of input images (up to the
    # workflow's max_images), and image-to-video when a video workflow is
    # configured -- no reference-to-video or music workflows wired up.
    "comfyui": {
        "supports_reference_images": True,
        "supports_video": bool(config.COMFYUI.get("video_workflow")),
        "supports_music": False,
    },
}

# What each job kind needs from a provider (None: every provider makes images).
_NEEDS = {"image": None, "video": "supports_video", "video_reference": "supports_video_reference",
          "music": "supports_music"}
for _name, _caps in CAPABILITIES.items():
    _caps.setdefault("supports_video_reference", _name == "fal")


def default_for(kind: str) -> str:
    """The provider a job of this kind uses when the node doesn't pick one:
    config.IMAGE_PROVIDER / VIDEO_PROVIDER, falling back to fal for what the
    default can't do (e.g. music while images and video run on ComfyUI)."""
    name = {"image": config.IMAGE_PROVIDER, "video": config.VIDEO_PROVIDER,
            "video_reference": config.VIDEO_PROVIDER}.get(kind, config.PROVIDER)
    need = _NEEDS.get(kind)
    if need and not CAPABILITIES.get(name, {}).get(need):
        return "fal"
    return name


def provider_for(kind: str, name: str = None):
    """The Provider for one job: `name` (an Image/Video node's pick) or the
    kind's default -- refusing one that can't do this kind."""
    name = name or default_for(kind)
    if name not in AVAILABLE_PROVIDERS:
        raise ValueError(f"unknown visuals provider: {name!r}")
    need = _NEEDS.get(kind)
    if need and not CAPABILITIES[name].get(need):
        what = {"video": "video", "video_reference": "reference-to-video", "music": "music"}[kind]
        raise RuntimeError(f"the {name} provider can't make {what} -- pick another provider on the node")
    return get_provider(name)

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
    elif name == "comfyui":
        from .comfyui import ComfyUIProvider
        instance = ComfyUIProvider()
    else:
        raise ValueError(f"unknown visuals provider: {name!r}")

    _instances[name] = instance
    return instance
