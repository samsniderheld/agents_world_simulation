"""Shared JSON response helper for both blueprints (history/routes.py,
agents/routes.py)."""

import json

from flask import Response


def json_response(payload, status=200):
    # Plain json.dumps (with default=str, same as the rest of this app's
    # JSON output) instead of Flask's jsonify -- keeps datetime/dataclass
    # leftovers from breaking a response the same defensive way the rest
    # of the app already handles them.
    return Response(json.dumps(payload, default=str), status=status, mimetype="application/json")
