"""Named, saved copies of canvases -- the "Saved graphs" library a canvas
can save itself into and load from later (as a template added alongside
what's there, or to replace it outright).

A saved graph is a *bundle*: the canvas's own nodes/edges, plus the inner
canvas of every Storyboard node on it (recursively, keyed by the scope it
had when saved), so a loaded Storyboard isn't an empty shell. Like
graph_store.py this is opaque to node internals -- remapping ids on load is
the frontend's job (frontend/src/flow/useGraphLibrary.ts).

Global on purpose, like the style library: a saved graph isn't tied to one
city, and deleting a city doesn't touch it. A graph loaded into a different
city keeps its Agent/Location nodes, which reconcile to "missing" there.
"""

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

_LIBRARY_DIR = Path(__file__).parent / "data" / "library"
_SAFE_ID = re.compile(r"^lib_[a-f0-9]{8}$")
_lock = threading.Lock()


def _path(graph_id: str) -> Path:
    if not _SAFE_ID.match(graph_id or ""):
        raise ValueError(f"invalid saved-graph id: {graph_id!r}")
    return _LIBRARY_DIR / f"{graph_id}.json"


def list_graphs() -> list:
    """Summaries only (no node payloads), newest first."""
    with _lock:
        if not _LIBRARY_DIR.exists():
            return []
        out = []
        for p in _LIBRARY_DIR.glob("lib_*.json"):
            with open(p) as f:
                d = json.load(f)
            out.append({
                "id": d["id"], "name": d["name"], "created": d["created"],
                "source_scope": d.get("source_scope"),
                "node_count": len(d["root"].get("nodes", [])),
                "storyboard_count": len(d.get("storyboards", {})),
            })
    return sorted(out, key=lambda d: d["created"], reverse=True)


def get_graph(graph_id: str) -> dict:
    path = _path(graph_id)
    with _lock:
        if not path.exists():
            raise KeyError(graph_id)
        with open(path) as f:
            return json.load(f)


def save_graph(name: str, root: dict, storyboards: dict = None, source_scope: str = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("a saved graph needs a name")
    graph_id = f"lib_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": graph_id, "name": name, "created": datetime.now().isoformat(),
        "source_scope": source_scope,
        "root": {"nodes": root.get("nodes", []), "edges": root.get("edges", [])},
        "storyboards": {
            scope: {"nodes": g.get("nodes", []), "edges": g.get("edges", [])}
            for scope, g in (storyboards or {}).items()
        },
    }
    with _lock:
        _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        path = _path(graph_id)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=2)
        tmp.replace(path)
    return doc


def delete_graph(graph_id: str) -> None:
    path = _path(graph_id)
    with _lock:
        if path.exists():
            path.unlink()
