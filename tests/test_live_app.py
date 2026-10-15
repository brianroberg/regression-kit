"""Integration tests: the live_app fixture driving tests/sample_app.py end to end."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
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


ENV_CONFTEST = """
import sys
import pytest
from regression_kit import LiveAppConfig

@pytest.fixture(scope="session")
def live_app_config():
    return LiveAppConfig(
        command=[sys.executable, {app!r}, "{{port}}"],
        ready_path="/health",
        env={{"RK_CONFIG_VAR": "from-config"}},
        inherit_env={inherit!r},
        startup_timeout=20,
    )
"""

ENV_TEST = """
import urllib.error
import urllib.request

def fetch(live_app, name):
    try:
        with urllib.request.urlopen(live_app.url(f"/env/{name}"), timeout=5) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
        return None

def test_env(live_app):
    assert fetch(live_app, "RK_CONFIG_VAR") == "from-config"
    assert fetch(live_app, "PATH") is not None
    assert fetch(live_app, "RK_PARENT_SECRET") == %r
"""


def test_inherit_env_true_passes_the_parent_environment(pytester, monkeypatch) -> None:
    monkeypatch.setenv("RK_PARENT_SECRET", "from-parent")
    pytester.makeconftest(ENV_CONFTEST.format(app=str(SAMPLE_APP), inherit=True))
    pytester.makepyfile(ENV_TEST % "from-parent")
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)


def test_inherit_env_false_passes_only_the_allowlist_and_config_env(pytester, monkeypatch) -> None:
    monkeypatch.setenv("RK_PARENT_SECRET", "from-parent")
    pytester.makeconftest(ENV_CONFTEST.format(app=str(SAMPLE_APP), inherit=False))
    pytester.makepyfile(ENV_TEST % None)
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)


MODE_CONFTEST = """
import sys
import pytest
from regression_kit import LiveAppConfig

@pytest.fixture(scope="session")
def live_app_config():
    return LiveAppConfig(
        command=[sys.executable, {app!r}, "{{port}}"],
        ready_path="/health",
        env={env!r},
        startup_timeout=20,
    )
"""

PIDS_TEST = """
import json
import re
import time

def test_records_pids(live_app):
    tail = live_app.output_tail()
    pids = {{name: int(pid) for name, pid in re.findall(r"(holder|child) pid (\\d+)", tail)}}
    pids["server"] = live_app.process.pid
    assert set(pids) == {expected!r}, tail
    with open("state.json", "w") as fh:
        json.dump({{"pids": pids, "test_done_at": time.time()}}, fh)
"""


def _kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _recorded_pids(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())["pids"]


def test_teardown_does_not_hang_when_a_grandchild_holds_the_pipe(pytester) -> None:
    # The server spawns ``sleep 600`` in a NEW session (outside the group the
    # fixture signals) with the output pipe inherited. After the server is gone
    # the reader thread stays blocked in read(); teardown must still finish, and
    # the session must end, within the 5 s join grace plus a little.
    pytester.makeconftest(
        MODE_CONFTEST.format(app=str(SAMPLE_APP), env={"SAMPLE_APP_HOLD_PIPE": "1"})
    )
    pytester.makepyfile(PIDS_TEST.format(expected={"holder", "server"}))
    state_file = pytester.path / "state.json"
    try:
        result = pytester.runpytest_subprocess("-p", "no:cacheprovider", timeout=60)
        finished_at = time.time()
        state = json.loads(state_file.read_text())
        result.assert_outcomes(passed=1, warnings=1)
        assert finished_at - state["test_done_at"] < 10, "teardown took too long"
        result.stdout.fnmatch_lines(["*still holding the server's output pipe*"])
        assert _pid_alive(state["pids"]["holder"]), "the holder should have outlived the fixture"
    finally:
        for pid in _recorded_pids(state_file).values():
            _kill_quietly(pid)


def test_server_ignoring_sigterm_is_killed_within_the_grace_period(pytester) -> None:
    # Pins the SIGKILL fallback: SIGTERM is ignored, so only the kill after the
    # 5 s grace can end the server.
    pytester.makeconftest(
        MODE_CONFTEST.format(app=str(SAMPLE_APP), env={"SAMPLE_APP_IGNORE_TERM": "1"})
    )
    pytester.makepyfile(PIDS_TEST.format(expected={"server"}))
    state_file = pytester.path / "state.json"
    try:
        pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)
        finished_at = time.time()
        state = json.loads(state_file.read_text())
        assert not _pid_alive(state["pids"]["server"]), "server survived teardown"
        assert finished_at - state["test_done_at"] < 8, "teardown took too long"
    finally:
        for pid in _recorded_pids(state_file).values():
            _kill_quietly(pid)


def test_teardown_kills_the_whole_process_group(pytester) -> None:
    # Pins the group kill: the server ignores SIGTERM and has an in-group child
    # (``sleep 600``). Signalling only the server pid would leave the child alive.
    pytester.makeconftest(
        MODE_CONFTEST.format(
            app=str(SAMPLE_APP),
            env={"SAMPLE_APP_IGNORE_TERM": "1", "SAMPLE_APP_SPAWN_CHILD": "1"},
        )
    )
    pytester.makepyfile(PIDS_TEST.format(expected={"child", "server"}))
    state_file = pytester.path / "state.json"
    try:
        pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)
        pids = json.loads(state_file.read_text())["pids"]
        assert not _pid_alive(pids["server"]), "server survived teardown"
        assert not _pid_alive(pids["child"]), "in-group child survived teardown"
    finally:
        for pid in _recorded_pids(state_file).values():
            _kill_quietly(pid)


def test_port_token_only_in_an_env_value_allocates_the_port(pytester) -> None:
    # Pins uses_port_token looking at env values: the command carries no {port},
    # the app reads PORT from its environment, and it must bind the port the
    # fixture reports (not an ephemeral one parsed from the output).
    pytester.makeconftest(
        """
        import sys
        import pytest
        from regression_kit import LiveAppConfig

        @pytest.fixture(scope="session")
        def live_app_config():
            return LiveAppConfig(
                command=[sys.executable, %r],
                ready_path="/health",
                env={"PORT": "{port}"},
                startup_timeout=20,
            )
        """
        % str(SAMPLE_APP)
    )
    pytester.makepyfile(
        """
        import urllib.request

        def test_port(live_app):
            with urllib.request.urlopen(live_app.url("/env/PORT"), timeout=5) as resp:
                assert resp.read().decode() == str(live_app.port)
            assert live_app.env["PORT"] == str(live_app.port)
        """
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)
