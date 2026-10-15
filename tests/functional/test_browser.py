"""Real-browser tests: pytest-playwright's ``page`` against ``live_app``.

These are the one path the rest of the suite cannot prove: that a marked test
really gets a Playwright page pointed at the live sample app. Without Chromium
they are skipped by the kit's own guard (or error under ``--require-browser``);
the kit's CI browser job (docs/ci/kit-ci.yml) runs them for real.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.functional


def test_root_renders_the_sample_app_body(live_app, page) -> None:
    response = page.goto(live_app.url("/"))
    assert response is not None and response.ok
    assert page.locator("body").inner_text().strip() == "ok"


def test_health_body(live_app, page) -> None:
    response = page.request.get(live_app.url("/health"))
    assert response.status == 200
    assert response.text() == "ok"


def test_clicking_the_button_runs_javascript(live_app, page) -> None:
    # A plain HTTP fetch of /page never contains "clicked" (tests/test_sample_app.py);
    # only a browser that executed the page's script does. This is the assertion
    # that proves a real browser ran, not merely an HTTP client.
    page.goto(live_app.url("/page"))
    assert page.title() == "regression-kit sample"
    assert page.locator("#result").inner_text() == "not clicked"
    page.locator("#clicker").click()
    assert page.locator("#result").inner_text() == "clicked"
