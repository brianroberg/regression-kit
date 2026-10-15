"""pytest plugin: the ``functional`` marker, the browser guard and the ``live_app`` fixture.

Loaded automatically through the ``pytest11`` entry point declared in pyproject.toml.
"""

from __future__ import annotations

import os

import pytest

from regression_kit._core import browser_available
from regression_kit._live import LiveAppConfig, start_live_app, stop_live_app

REQUIRE_BROWSER_ENV = "REGRESSION_KIT_REQUIRE_BROWSER"
_REQUIRED_FAIL = pytest.StashKey[str]()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("regression-kit")
    group.addoption(
        "--require-browser",
        action="store_true",
        default=False,
        help="Fail (instead of skip) marked tests when Playwright's Chromium is not installed. "
        f"Also enabled by {REQUIRE_BROWSER_ENV}=1.",
    )
    parser.addini(
        "regression_kit_marker",
        "Name of the marker that identifies browser/e2e tests (default: functional).",
        default="functional",
    )


def _marker_name(config: pytest.Config) -> str:
    return str(config.getini("regression_kit_marker") or "functional")


def _browser_required(config: pytest.Config) -> bool:
    if config.getoption("--require-browser"):
        return True
    return os.environ.get(REQUIRE_BROWSER_ENV, "").strip().lower() in ("1", "true", "yes")


def pytest_configure(config: pytest.Config) -> None:
    name = _marker_name(config)
    config.addinivalue_line(
        "markers",
        f"{name}: browser/e2e regression test against a live app (regression-kit). "
        "Skipped when Playwright's Chromium is missing unless --require-browser is given.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    name = _marker_name(config)
    marked = [item for item in items if item.get_closest_marker(name) is not None]
    if not marked:
        return
    ok, reason = browser_available()
    if ok:
        return
    message = f"browser unavailable: {reason}"
    required = _browser_required(config)
    for item in marked:
        if required:
            item.stash[_REQUIRED_FAIL] = message
        else:
            item.add_marker(pytest.mark.skip(reason=message))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    message = item.stash.get(_REQUIRED_FAIL, None)
    if message is not None:
        pytest.fail(f"{message} (--require-browser or {REQUIRE_BROWSER_ENV}=1 is set)")


@pytest.fixture(scope="session")
def live_app(request: pytest.FixtureRequest):
    """The app under test, started from the user's ``live_app_config`` fixture.

    Session-scoped: one server per test session. Define a session-scoped
    ``live_app_config`` fixture (normally in conftest.py) returning a
    :class:`regression_kit.LiveAppConfig`.
    """
    try:
        config = request.getfixturevalue("live_app_config")
    except pytest.FixtureLookupError:
        pytest.fail(
            "regression-kit: the live_app fixture needs a session-scoped fixture named "
            "'live_app_config' that returns a regression_kit.LiveAppConfig. Define it in "
            "your conftest.py.",
            pytrace=False,
        )
    if not isinstance(config, LiveAppConfig):
        pytest.fail(
            "regression-kit: the live_app_config fixture must return a "
            f"regression_kit.LiveAppConfig, not {type(config).__name__}.",
            pytrace=False,
        )
    __tracebackhide__ = True
    app = start_live_app(config)  # raises LiveAppStartupError with the output tail
    try:
        yield app
    finally:
        stop_live_app(app)
