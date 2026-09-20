"""Persists the node-based UI's own canvas state -- one small JSON
document per "scope" (the city canvas itself, or one entity's drilled-in
canvas: "city", "agent:<char_id>", "place:<place_id>", "scratch:<board_id>",
matching frontend/src/routes/router.ts's Scope type).

Deliberately opaque: this module doesn't know what a "node" or "edge" is
-- it stores whatever `nodes`/`edges` arrays the client sends verbatim,
because the node schema is still changing fast during this rewrite and a
server that parsed node internals would need editing every time a node
type gains a field. All this validates is the envelope (rev for
optimistic concurrency, scope for the filename) and the general shape.

Nodes hold references to domain entities (a char_*/place_* id), never
copies -- reconciling those references against the live city (an entity
appearing with no node yet, or a node whose entity has since vanished) is
entirely a frontend concern, not this module's.
"""

import json
import re
import threading
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
_GRAPHS_DIR = DATA_DIR / "graphs"

_lock = threading.Lock()

_SAFE_SCOPE = re.compile(r"^[a-zA-Z0-9_:-]+$")


class RevConflict(Exception):
    """Raised when a PUT's `rev` doesn't match what's on disk -- the
    caller already holds the current document (passed to the
    constructor) to merge onto and retry with."""

    def __init__(self, current: dict):
        super().__init__("graph document has moved on -- rev conflict")
        self.current = current


def _path_for(scope: str) -> Path:
    if not _SAFE_SCOPE.match(scope):
        raise ValueError(f"invalid scope: {scope!r}")
    # ':' is valid in a Unix filename but let's not tempt fate across
    # filesystems -- "agent:char_x" -> "agent_char_x.json".
    return _GRAPHS_DIR / f"{scope.replace(':', '_')}.json"


def _empty(scope: str) -> dict:
    return {
        "scope": scope,
        "version": 1,
        "rev": 0,
        "updated": None,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": [],
        "edges": [],
    }


def get_graph(scope: str) -> dict:
    """Never 404s -- an unseeded scope is just an empty graph the client
    hasn't saved anything into yet, not an error."""
    path = _path_for(scope)
    with _lock:
        if not path.exists():
            return _empty(scope)
        with open(path) as f:
            return json.load(f)


def save_graph(scope: str, payload: dict) -> dict:
    """Optimistic concurrency: the client must submit the `rev` it last
    read: if the file has moved on since, raises RevConflict(current)
    rather than silently overwriting a concurrent edit (two tabs open on
    the same canvas, most realistically)."""
    path = _path_for(scope)
    with _lock:
        current = json.load(open(path)) if path.exists() else _empty(scope)
        submitted_rev = payload.get("rev")
        if submitted_rev != current["rev"]:
            raise RevConflict(current)

        doc = {
            "scope": scope,
            "version": payload.get("version", current["version"]),
            "rev": current["rev"] + 1,
            "updated": datetime.now().isoformat(),
            "viewport": payload.get("viewport", current["viewport"]),
            "nodes": payload.get("nodes", []),
            "edges": payload.get("edges", []),
        }
        _GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=2)
        tmp.replace(path)
        return doc


