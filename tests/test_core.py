"""Unit and property tests for the pure functions in regression_kit._core."""

from __future__ import annotations

import socket

import pytest
from hypothesis import given
from hypothesis import strategies as st

from regression_kit._core import (
    browser_available,
    free_port,
    is_ready,
    merge_env,
    parse_port,
    substitute_port,
)

# --- parse_port -------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "INFO:     Uvicorn running on http://127.0.0.1:45321 (Press CTRL+C to quit)",
        " * Running on http://127.0.0.1:45321",
        "[2026-10-15 12:00:00 -0400] [123] [INFO] Listening at: http://127.0.0.1:45321 (123)",
        "Serving on http://localhost:45321",
        "bound 0.0.0.0:45321",
    ],
)
def test_parse_port_default_pattern_recognises_common_servers(line: str) -> None:
    assert parse_port(line, None) == 45321


def test_parse_port_returns_none_without_a_port() -> None:
    assert parse_port("INFO:     Application startup complete.", None) is None
    assert parse_port("", None) is None


def test_parse_port_custom_pattern() -> None:
    assert parse_port("listening on port 8123", r"port (\d+)") == 8123
    assert parse_port("nothing here", r"port (\d+)") is None


def test_parse_port_rejects_out_of_range_values() -> None:
    assert parse_port("http://127.0.0.1:99999", None) is None
    assert parse_port("http://127.0.0.1:0", None) is None


_port_free_text = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Zs")),
).filter(lambda s: parse_port(s, None) is None)


@given(prefix=_port_free_text, port=st.integers(1, 65535), suffix=_port_free_text)
def test_parse_port_recovers_embedded_loopback_port(prefix: str, port: int, suffix: str) -> None:
    assert parse_port(f"{prefix} 127.0.0.1:{port} {suffix}", None) == port


@given(text=st.text(alphabet=st.characters(categories=("L", "P", "Zs"))))
def test_parse_port_without_digits_is_none(text: str) -> None:
    assert parse_port(text, None) is None


# --- merge_env --------------------------------------------------------------


def test_merge_env_substitutes_port_in_values_only() -> None:
    merged = merge_env({"HOME": "/h"}, {"URL": "http://127.0.0.1:{port}/x", "{port}": "k"}, 8000)
    assert merged["URL"] == "http://127.0.0.1:8000/x"
    assert merged["{port}"] == "k"  # keys are left alone
    assert merged["HOME"] == "/h"


def test_merge_env_returns_a_new_dict() -> None:
    base = {"A": "1"}
    merged = merge_env(base, {"B": "2"}, 1)
    assert merged == {"A": "1", "B": "2"}
    assert base == {"A": "1"}


_env_text = st.text(alphabet=st.characters(categories=("L", "N", "P")), max_size=20)


@given(
    base=st.dictionaries(_env_text, _env_text, max_size=8),
    extra=st.dictionaries(_env_text, _env_text, max_size=8),
    port=st.integers(1, 65535),
)
def test_merge_env_extra_wins_and_base_survives(
    base: dict[str, str], extra: dict[str, str], port: int
) -> None:
    merged = merge_env(base, extra, port)
    for key, value in extra.items():
        assert merged[key] == value.replace("{port}", str(port))
    for key, value in base.items():
        if key not in extra:
            assert merged[key] == value
    assert set(merged) == set(base) | set(extra)


# --- substitute_port --------------------------------------------------------


def test_substitute_port_replaces_token_anywhere_in_an_argument() -> None:
    cmd = ["uvicorn", "app:app", "--port", "{port}", "--root-path", "/p{port}"]
    assert substitute_port(cmd, 8001) == [
        "uvicorn",
        "app:app",
        "--port",
        "8001",
        "--root-path",
        "/p8001",
    ]


@given(cmd=st.lists(st.text().filter(lambda s: "{port}" not in s), max_size=6))
def test_substitute_port_leaves_commands_without_token_unchanged(cmd: list[str]) -> None:
    assert substitute_port(cmd, 1234) == list(cmd)


def test_substitute_port_accepts_any_sequence_and_returns_a_list() -> None:
    assert substitute_port(("a", "{port}"), 5) == ["a", "5"]


# --- free_port --------------------------------------------------------------


def test_free_port_is_bindable() -> None:
    port = free_port("127.0.0.1")
    assert 1024 <= port <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


# --- is_ready ---------------------------------------------------------------


def test_is_ready_false_when_nothing_listens() -> None:
    port = free_port("127.0.0.1")
    assert is_ready(f"http://127.0.0.1:{port}/", range(200, 500), timeout=0.5) is False


def test_is_ready_true_for_an_accepted_status(http_server) -> None:
    url, _ = http_server
    assert is_ready(f"{url}/health", {200}, timeout=1.0) is True
    assert is_ready(f"{url}/missing", range(200, 500), timeout=1.0) is True


def test_is_ready_false_when_status_not_accepted(http_server) -> None:
    url, _ = http_server
    assert is_ready(f"{url}/missing", {200}, timeout=1.0) is False


# --- browser_available ------------------------------------------------------


def test_browser_available_false_without_playwright(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("regression_kit._core.find_spec", lambda name: None)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    ok, reason = browser_available()
    assert ok is False
    assert "playwright" in reason and "not installed" in reason


def test_browser_available_false_without_chromium(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("regression_kit._core.find_spec", lambda name: object())
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    (tmp_path / "firefox-1234").mkdir()
    ok, reason = browser_available()
    assert ok is False
    assert "chromium" in reason and str(tmp_path) in reason


def test_browser_available_true_with_chromium_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("regression_kit._core.find_spec", lambda name: object())
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    (tmp_path / "chromium-1187").mkdir()
    ok, reason = browser_available()
    assert ok is True
    assert "chromium-1187" in reason


def test_browser_available_uses_platform_default_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("regression_kit._core.find_spec", lambda name: object())
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr("regression_kit._core.Path.home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("regression_kit._core.sys.platform", "linux")
    (tmp_path / ".cache" / "ms-playwright" / "chromium_headless_shell-1187").mkdir(parents=True)
    ok, _ = browser_available()
    assert ok is True
    monkeypatch.setattr("regression_kit._core.sys.platform", "darwin")
    ok, reason = browser_available()
    assert ok is False
    assert "Library/Caches/ms-playwright" in reason
