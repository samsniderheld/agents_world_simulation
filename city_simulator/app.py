"""The primary interface: a local Flask app serving the frontend (templates/
+ static/) plus a small JSON/SSE API for both halves of the app -- history
generation (history/routes.py, /api/history/*) and the agent simulation
(agents/routes.py, /api/agents/*). Each runs on its own background thread
with its own status (see each package's jobs.py), so the frontend can drive
both independently: generate a history in the first tab, then (once it's
done) run agents seeded from it in the second.

Usage:
    python3 app.py
"""

import logging

from flask import Flask, render_template
from werkzeug.serving import make_server

from agents import jobs as agents_jobs
from agents.routes import bp as agents_bp
from citystate import store as citystate
from citystate.routes import bp as city_bp
from history.routes import bp as history_bp
from visuals.routes import bp as visuals_bp

# The frontend is the interface now; keep the terminal quiet (matches the
# old bare http.server Handler's log_message no-op).
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(history_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(visuals_bp)
    app.register_blueprint(city_bp)

    # citystate.store.get() lazily reads a previously-saved city off disk
    # on its own -- the one thing it can't derive by itself is the agent
    # roster (agents-package-specific), so that's hydrated explicitly here.
    saved_city = citystate.get()
    if saved_city is not None:
        agents_jobs.set_history_roster(saved_city)

    @app.get("/")
    def index():
        return render_template("index.html")

    return app


# Fixed, not ephemeral -- the URL survives a restart, so the workflow is
# refreshing whatever tab you already have open rather than a new one
# opening every time (see main()). If something else on this machine is
# already using this port, change it here.
PORT = 8420


def main():
    app = create_app()
    # make_server (not app.run()) so threaded=True is available -- the
    # long-lived SSE stream would otherwise block other requests.
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    url = f"http://127.0.0.1:{srv.server_port}/"
    print(f"Serving City Simulator at {url} -- refresh your existing tab, or open it (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
