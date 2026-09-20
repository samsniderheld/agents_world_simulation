"""Flask blueprint for the node-based UI's own canvas persistence --
GET/PUT one JSON document per scope. See graph_store.py's docstring for
why this stays deliberately opaque to node/edge internals.
"""

from flask import Blueprint, request

from jsonutil import json_response

from . import graph_store

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
