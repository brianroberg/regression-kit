"""The sample app itself: the routes the functional (browser) tests rely on.

Pinned without a browser so a change to ``tests/sample_app.py`` cannot silently
turn the browser tests into tests of nothing.
"""

from __future__ import annotations

import threading
import urllib.request
from http.server import HTTPServer

import pytest

from tests.sample_app import Handler


@pytest.fixture
def sample_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _get(url: str) -> tuple[int, str, str]:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode()


def test_page_serves_html_with_a_button_and_a_script(sample_server) -> None:
    status, content_type, body = _get(f"{sample_server}/page")
    assert status == 200
    assert content_type.startswith("text/html")
    assert "<title>regression-kit sample</title>" in body
    assert 'id="clicker"' in body and 'id="result"' in body
    # The result text is written ONLY by the script, so a plain HTTP fetch never
    # sees it; only a browser that ran the JS can.
    assert "clicked" in body and ">clicked<" not in body
    assert "<script>" in body
