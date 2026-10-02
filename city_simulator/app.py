"""The primary interface: a local Flask app serving the React/React-Flow
frontend (frontend/, built into static/dist/ -- see frontend/vite.config.ts)
plus a small JSON API for all four halves of the app -- history generation
(history/routes.py, /api/history/*), the agent simulation (agents/routes.py,
/api/agents/*), media generation (visuals/routes.py, /api/visuals/*), and
the persisted city (citystate/routes.py, /api/city/*). Each job-style
endpoint runs on its own background thread with its own status (see each
package's jobs.py), so the frontend can drive them independently.

Usage:
    python3 app.py                                   # serve the built SPA
    (cd frontend && npm run dev)                      # SPA dev server, proxies /api to this process

Serving beyond this machine (e.g. a RunPod public URL): set APP_PASSWORD
(and optionally APP_USER, default "admin") so every page and API call needs
a login, and APP_HOST=0.0.0.0 so it listens on all interfaces. The app
refuses to listen beyond localhost without a password -- anyone who could
reach it could otherwise run jobs on your GPU and delete your cities.
"""

import hmac
import logging
import os
import sys

from flask import Flask, Response, request, send_from_directory
from werkzeug.serving import make_server

from agents import jobs as agents_jobs
from agents.routes import bp as agents_bp
from citystate import store as citystate
from citystate.graph_routes import bp as graph_bp
from citystate.graph_routes import library_bp as graph_library_bp
from citystate.routes import bp as city_bp
from history.routes import bp as history_bp
from theme_routes import bp as themes_bp
from visuals.routes import bp as visuals_bp
from visuals.styles_routes import bp as styles_bp

# The frontend is the interface now; keep the terminal quiet (matches the
# old bare http.server Handler's log_message no-op).
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_DIST_DIR = "static/dist"


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(history_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(visuals_bp)
    app.register_blueprint(city_bp)
    app.register_blueprint(graph_bp)
    app.register_blueprint(graph_library_bp)
    app.register_blueprint(styles_bp)
    app.register_blueprint(themes_bp)

    # citystate.store.get() lazily reads a previously-saved city off disk
    # on its own -- the one thing it can't derive by itself is the agent
    # roster (agents-package-specific), so that's hydrated explicitly here.
    saved_city = citystate.get()
    if saved_city is not None:
        agents_jobs.set_history_roster(saved_city)

    _install_login(app)

    # The SPA owns client-side routing (/, /c/<city>, /c/<city>/agent/<id>,
    # /c/<city>/place/<id>, /c/<city>/gallery, /scratch/<id>,
    # /storyboard/<id> -- see frontend/src/routes/router.ts), so every one of
    # those paths serves the same built index.html and lets it route from
    # there client-side. A matched /api/* GET (POST/DELETE never reach
    # this GET-only rule at all) is claimed by the blueprints above before
    # this ever runs; an *unmatched* one still 404s here rather than
    # silently returning the SPA shell, which would hide a real API bug
    # behind a confusing 200.
    @app.get("/")
    @app.get("/<path:_client_route>")
    def spa(_client_route: str = ""):
        if _client_route.startswith("api/"):
            return "not found", 404
        return send_from_directory(_DIST_DIR, "index.html")

    return app


def _install_login(app: Flask) -> None:
    """HTTP Basic auth on every request when APP_PASSWORD is set. The
    browser asks once and then sends the credentials with every page and
    API request on its own, so the frontend needs no changes."""
    password = os.environ.get("APP_PASSWORD")
    if not password:
        return
    user = os.environ.get("APP_USER", "admin")

    @app.before_request
    def require_login():
        auth = request.authorization
        if auth and hmac.compare_digest(auth.username or "", user) and \
                hmac.compare_digest(auth.password or "", password):
            return None
        return Response("Login required.", 401, {"WWW-Authenticate": 'Basic realm="City Simulator"'})


# Fixed, not ephemeral -- the URL survives a restart, so the workflow is
# refreshing whatever tab you already have open rather than a new one
# opening every time (see main()). If something else on this machine is
# already using this port, change it here.
PORT = 8420


def main():
    host = os.environ.get("APP_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost") and not os.environ.get("APP_PASSWORD"):
        sys.exit(f"Refusing to listen on {host} without a login: set APP_PASSWORD (and optionally APP_USER).")
    app = create_app()
    # make_server (not app.run()) so threaded=True is available -- a slow
    # job-status poll or media download must not block other requests.
    srv = make_server(host, PORT, app, threaded=True)
    url = f"http://{host}:{srv.server_port}/"
    login = " (login required)" if os.environ.get("APP_PASSWORD") else ""
    print(f"Serving City Simulator at {url}{login} -- refresh your existing tab, or open it (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
