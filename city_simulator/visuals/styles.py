"""A small global style library -- reusable prompt + reference-image
bundles a Style node points at (frontend/src/flow/nodes/StyleNode.tsx).

Deliberately lives here in visuals/data/, not citystate/data/: a style is
independent of any particular city (reusable across cities and scratch
boards alike, per the design spec), so it must survive a city being
deleted or regenerated -- citystate/store.py's delete()/replace() never
touch this file.
"""

import json
import threading
import uuid
from pathlib import Path

_STYLES_PATH = Path(__file__).parent / "data" / "styles.json"
_lock = threading.Lock()


def _read() -> list:
    if not _STYLES_PATH.exists():
        return []
    with open(_STYLES_PATH) as f:
        return json.load(f)


def _write(styles: list) -> None:
    _STYLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STYLES_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(styles, f, indent=2)
    tmp.replace(_STYLES_PATH)


def list_styles() -> list:
    with _lock:
        return _read()


def create_style(name: str, style_prompt: str, negative_prompt: str = "", reference_images: list = None, strength: float = 0.6) -> dict:
    style = {
        "id": f"sty_{uuid.uuid4().hex[:8]}",
        "name": name,
        "style_prompt": style_prompt,
        # Captured for a future provider that exposes an equivalent knob
        # -- see visuals/routes.py's generate_image() docstring for why
        # today's fal/Gemini-based provider doesn't forward these two.
        "negative_prompt": negative_prompt,
        "strength": strength,
        "reference_images": reference_images or [],
    }
    with _lock:
        styles = _read()
        styles.append(style)
        _write(styles)
    return style


def update_style(style_id: str, **fields) -> dict:
    """Partial update -- a Style node edits its library entry in place
    (name/style_prompt/negative_prompt/strength/reference_images), so
    every canvas pointing at this styleId sees the change next time it
    loads, matching "reusable across cities" rather than forking a copy
    per node. Raises if no such style."""
    with _lock:
        styles = _read()
        for s in styles:
            if s["id"] == style_id:
                s.update({k: v for k, v in fields.items() if v is not None})
                _write(styles)
                return s
    raise KeyError(style_id)


def delete_style(style_id: str) -> bool:
    with _lock:
        styles = _read()
        remaining = [s for s in styles if s["id"] != style_id]
        if len(remaining) == len(styles):
            return False
        _write(remaining)
        return True
