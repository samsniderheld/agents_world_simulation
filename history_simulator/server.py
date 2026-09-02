"""Serves index.html + history.json so the generated history can be viewed
in a browser. Called automatically at the end of generate.py; run standalone
(`python3 server.py`) to re-view an already-generated history.json without
regenerating anything.

Usage:
    python3 server.py
"""

import functools
import http.server
import os
import webbrowser

DIRECTORY = os.path.dirname(os.path.abspath(__file__))


def serve(directory: str = DIRECTORY, open_browser: bool = True):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"Serving history viewer at {url} (Ctrl+C to stop)")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    serve()
