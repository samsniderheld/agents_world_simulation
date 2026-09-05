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
import webbrowser

from flask import Flask, render_template
from werkzeug.serving import make_server

from agents.routes import bp as agents_bp
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

    @app.get("/")
    def index():
        return render_template("index.html")

    return app


def main():
    app = create_app()
    # make_server (not app.run()) so an ephemeral port (0) resolves to a
    # real port we can print/open a browser to, and threaded=True so the
    # long-lived SSE stream doesn't block other requests.
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    url = f"http://127.0.0.1:{srv.server_port}/"
    print(f"Serving City Simulator at {url} (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
