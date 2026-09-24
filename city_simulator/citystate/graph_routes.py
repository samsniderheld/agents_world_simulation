"""Flask blueprint for the node-based UI's own canvas persistence --
GET/PUT one JSON document per scope. See graph_store.py's docstring for
why this stays deliberately opaque to node/edge internals.
"""

from flask import Blueprint, request

from jsonutil import json_response

from . import graph_library, graph_store

bp = Blueprint("graph", __name__, url_prefix="/api/graph")


@bp.get("/<scope>")
def get_graph(scope):
    try:
        return json_response(graph_store.get_graph(scope))
    except ValueError as e:
        return json_response({"error": str(e)}, status=400)


@bp.put("/<scope>")
def put_graph(scope):
    body = request.get_json(silent=True) or {}
    try:
        doc = graph_store.save_graph(scope, body)
        return json_response(doc)
    except ValueError as e:
        return json_response({"error": str(e)}, status=400)
    except graph_store.RevConflict as e:
        return json_response({"error": "rev conflict", "current": e.current}, status=409)


# ---- the saved-graphs library (graph_library.py) --------------------------
# A separate prefix rather than /api/graph/library, which would collide
# with the /<scope> routes above.
library_bp = Blueprint("graph_library", __name__, url_prefix="/api/graph-library")


@library_bp.get("/")
def list_saved():
    return json_response({"graphs": graph_library.list_graphs()})


@library_bp.post("/")
def save_saved():
    body = request.get_json(silent=True) or {}
    try:
        doc = graph_library.save_graph(
            body.get("name"), body.get("root") or {}, body.get("storyboards") or {}, body.get("source_scope"),
        )
    except ValueError as e:
        return json_response({"error": str(e)}, status=400)
    return json_response({"graph": {k: doc[k] for k in ("id", "name", "created")}})


@library_bp.get("/<graph_id>")
def get_saved(graph_id):
    try:
        return json_response({"graph": graph_library.get_graph(graph_id)})
    except ValueError as e:
        return json_response({"error": str(e)}, status=400)
    except KeyError:
        return json_response({"error": "no such saved graph"}, status=404)


@library_bp.delete("/<graph_id>")
def delete_saved(graph_id):
    try:
        graph_library.delete_graph(graph_id)
    except ValueError as e:
        return json_response({"error": str(e)}, status=400)
    return json_response({"ok": True})
