"""Integration tests: the live_app fixture driving tests/sample_app.py end to end."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

SAMPLE_APP = Path(__file__).with_name("sample_app.py")

CONFTEST_TEMPLATE = """
import pytest
from regression_kit import LiveAppConfig

@pytest.fixture(scope="session")
def live_app_config():
    return LiveAppConfig(
        command={command!r},
        ready_path="/health",
        ready_status={{200}},
        env={env!r},
        startup_timeout=20,
    )
"""

TEST_FILE = """
import json
import os
import urllib.request

def test_server_answers(live_app):
    with urllib.request.urlopen(live_app.url("/health"), timeout=5) as resp:
        assert resp.status == 200
        assert resp.read() == b"ok"
    assert live_app.base_url == f"http://127.0.0.1:{live_app.port}"
    assert live_app.process.poll() is None
    assert "sample_app starting" in live_app.output_tail()
    with open("state.json", "w") as fh:
        json.dump({"pid": live_app.process.pid, "port": live_app.port}, fh)

def test_second_test_shares_the_same_server(live_app):
    with open("state.json") as fh:
        state = json.load(fh)
    assert state["pid"] == live_app.process.pid
"""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _run(pytester: pytest.Pytester, command: list[str], env: dict[str, str]) -> dict:
    pytester.makeconftest(CONFTEST_TEMPLATE.format(command=command, env=env))
    pytester.makepyfile(TEST_FILE)
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)
    import json

    return json.loads((pytester.path / "state.json").read_text())


def test_live_app_with_port_token(pytester: pytest.Pytester) -> None:
    state = _run(pytester, [sys.executable, str(SAMPLE_APP), "{port}"], {"MODE": "token"})
    assert not _pid_alive(state["pid"]), "server process survived fixture teardown"


def test_live_app_with_parsed_port(pytester: pytest.Pytester) -> None:
    # No {port} anywhere: the plugin must read the port the app chose from its output.
    state = _run(pytester, [sys.executable, str(SAMPLE_APP)], {"MODE": "parsed"})
    assert state["port"] > 0
    assert not _pid_alive(state["pid"]), "server process survived fixture teardown"


def test_env_receives_substituted_port(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        CONFTEST_TEMPLATE.format(
            command=[sys.executable, str(SAMPLE_APP), "{port}"], env={"SAMPLE_PORT": "{port}"}
        )
    )
    pytester.makepyfile(
        """
        import os

        def test_env(live_app):
            # The server inherits SAMPLE_PORT; the test process does not. Prove the
            # substitution by comparing the configured env against the live port.
            assert live_app.config.env["SAMPLE_PORT"] == "{port}"
            assert live_app.env["SAMPLE_PORT"] == str(live_app.port)
        """
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)
