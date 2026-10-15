"""pytester tests for the plugin hooks: marker registration and the browser guard."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

MARKED_TEST = """
import pytest

@pytest.mark.functional
def test_browser_thing():
    assert True

def test_plain():
    assert True
"""


@pytest.fixture
def no_browser(monkeypatch):
    monkeypatch.setattr(
        "regression_kit.plugin.browser_available", lambda: (False, "no chromium (fake)")
    )


@pytest.fixture
def with_browser(monkeypatch):
    monkeypatch.setattr(
        "regression_kit.plugin.browser_available", lambda: (True, "found /fake/chromium-1")
    )


def test_functional_marker_is_registered(pytester: pytest.Pytester) -> None:
    result = pytester.runpytest("--markers")
    result.stdout.re_match_lines([r"@pytest\.mark\.functional: .*regression-kit.*"])


def test_marked_test_passes_under_strict_markers(pytester: pytest.Pytester, with_browser) -> None:
    pytester.makepyfile(MARKED_TEST)
    result = pytester.runpytest("--strict-markers")
    result.assert_outcomes(passed=2)


def test_marker_name_is_configurable(pytester: pytest.Pytester, no_browser) -> None:
    pytester.makeini("[pytest]\nregression_kit_marker = e2e\n")
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.e2e
        def test_e2e():
            assert True
        """
    )
    result = pytester.runpytest("--markers")
    result.stdout.re_match_lines([r"@pytest\.mark\.e2e: .*regression-kit.*"])
    result = pytester.runpytest("--strict-markers", "-rs")
    result.assert_outcomes(skipped=1)


def test_marked_test_is_skipped_without_browser(pytester: pytest.Pytester, no_browser) -> None:
    pytester.makepyfile(MARKED_TEST)
    result = pytester.runpytest("-rs")
    result.assert_outcomes(passed=1, skipped=1)
    result.stdout.fnmatch_lines(["*SKIPPED*no chromium (fake)*"])


def test_require_browser_flag_fails_marked_test(pytester: pytest.Pytester, no_browser) -> None:
    # The failure is raised in the setup phase (before any fixture such as a live
    # server or Playwright's own ``page`` runs), so pytest reports it as ERROR.
    pytester.makepyfile(MARKED_TEST)
    result = pytester.runpytest("--require-browser")
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*ERROR*test_browser_thing*", "*no chromium (fake)*"])
    assert result.ret != 0


def test_require_browser_env_fails_marked_test(
    pytester: pytest.Pytester, no_browser, monkeypatch
) -> None:
    monkeypatch.setenv("REGRESSION_KIT_REQUIRE_BROWSER", "1")
    pytester.makepyfile(MARKED_TEST)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*no chromium (fake)*"])
    assert result.ret != 0


def test_require_browser_env_zero_means_not_required(
    pytester: pytest.Pytester, no_browser, monkeypatch
) -> None:
    monkeypatch.setenv("REGRESSION_KIT_REQUIRE_BROWSER", "0")
    pytester.makepyfile(MARKED_TEST)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, skipped=1)


def test_marked_test_runs_untouched_with_browser(pytester: pytest.Pytester, with_browser) -> None:
    pytester.makepyfile(MARKED_TEST)
    result = pytester.runpytest("--require-browser", "-rs")
    result.assert_outcomes(passed=2)
    assert "SKIPPED" not in result.stdout.str()


def test_deselecting_marker_still_works(pytester: pytest.Pytester, no_browser) -> None:
    pytester.makepyfile(MARKED_TEST)
    result = pytester.runpytest("-m", "not functional")
    result.assert_outcomes(passed=1, deselected=1)


# --- live_app failure paths -------------------------------------------------


def _config_conftest(command: str, *args: str, **kwargs: object) -> str:
    """A conftest whose live_app_config runs ``python -c <command> <args...>``."""
    argv = "".join(f", {arg!r}" for arg in args)
    extras = "".join(f", {key}={value!r}" for key, value in kwargs.items())
    return f"""
import sys
import pytest
from regression_kit import LiveAppConfig

@pytest.fixture(scope="session")
def live_app_config():
    return LiveAppConfig(command=[sys.executable, "-c", {command!r}{argv}]{extras})
"""


USES_LIVE_APP = """
def test_uses_live_app(live_app):
    assert live_app.port
"""


def test_live_app_without_config_names_the_missing_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(USES_LIVE_APP)
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*live_app_config*LiveAppConfig*"])


def test_live_app_config_of_wrong_type_is_rejected(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import pytest

        @pytest.fixture(scope="session")
        def live_app_config():
            return {"command": ["x"]}
        """
    )
    pytester.makepyfile(USES_LIVE_APP)
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*live_app_config*must return*LiveAppConfig*dict*"])


def test_live_app_command_that_exits_early(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        _config_conftest("import sys; print('boom: no database'); sys.exit(3)", startup_timeout=10)
    )
    pytester.makepyfile(USES_LIVE_APP)
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*LiveAppStartupError: app exited*code 3*", "*boom: no database*"])


def test_live_app_port_never_printed(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        _config_conftest(
            "import time; print('started but silent', flush=True); time.sleep(30)",
            startup_timeout=1.5,
        )
    )
    pytester.makepyfile(USES_LIVE_APP)
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*LiveAppStartupError: app did not report a port*1.5*", "*started but silent*"]
    )


def test_live_app_readiness_timeout(pytester: pytest.Pytester) -> None:
    # Binds the port so the plugin knows where to look, but never answers HTTP.
    pytester.makeconftest(
        _config_conftest(
            "import socket, sys, time; s = socket.socket(); "
            "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen(); "
            "print('bound, not serving', flush=True); time.sleep(30)",
            "{port}",
            startup_timeout=2.0,
        )
    )
    pytester.makepyfile(USES_LIVE_APP)
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*LiveAppStartupError: app did not answer*2.0*", "*bound, not serving*"]
    )


def test_require_browser_fails_before_fixtures_run(pytester: pytest.Pytester, no_browser) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def exploding():
            raise RuntimeError("fixture ran")

        @pytest.mark.functional
        def test_browser_thing(exploding):
            assert True
        """
    )
    result = pytester.runpytest("--require-browser")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*no chromium (fake)*"])
    assert "fixture ran" not in result.stdout.str()
