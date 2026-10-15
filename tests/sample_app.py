"""A tiny stdlib HTTP server used as the app under test in the integration tests.

Usage: ``python sample_app.py [PORT]``. With no PORT it binds an ephemeral port
and prints ``Serving on http://127.0.0.1:PORT`` so the plugin can parse it.
``/`` and ``/health`` answer 200; ``/env/NAME`` answers 200 with the value of the
environment variable NAME (404 if unset); anything else 404.
"""

from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path.startswith("/env/"):
            value = os.environ.get(self.path[len("/env/") :])
            status = 200 if value is not None else 404
            body = value.encode() if value is not None else b"unset"
        else:
            status = 200 if self.path in ("/", "/health") else 404
            body = b"ok" if status == 200 else b"missing"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"request: {fmt % args}", flush=True)


def main(argv: list[str]) -> None:
    port = int(argv[1]) if len(argv) > 1 else 0
    server = HTTPServer(("127.0.0.1", port), Handler)
    print("sample_app starting", flush=True)
    print(f"Serving on http://127.0.0.1:{server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
