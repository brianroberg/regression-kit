"""Shared fixtures for the regression-kit test suite."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/missing")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        status = 200 if self.path in ("/", "/health") else 404
        self.send_response(status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:  # silence request logging
        pass


@pytest.fixture
def http_server():
    """An in-process stdlib HTTP server on an ephemeral port: yields (base_url, port)."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def pytester(pytester):
    """pytester with the pytest-playwright plugin disabled in the INNER run.

    pytest-playwright (0.10) wraps every ``pytest_runtest_call`` in Playwright's
    soft-assertion scope, which cannot nest: an in-process ``runpytest`` inside a
    test fails every inner test with "nested soft assertion scopes are not
    supported". The inner runs here test regression-kit, never Playwright, so
    the plugin is dropped from them. Only the kit's own functional tests use it.
    """
    inprocess = pytester.runpytest_inprocess

    def runpytest_inprocess(*args, **kwargs):
        return inprocess("-p", "no:playwright", *args, **kwargs)

    pytester.runpytest_inprocess = runpytest_inprocess
    return pytester
