"""Unit tests for LiveAppConfig validation and the LiveApp dataclass."""

from __future__ import annotations

import pytest

from regression_kit import LiveAppConfig


def test_command_given_as_a_string_is_rejected_at_construction() -> None:
    with pytest.raises(TypeError, match="command must be a sequence of arguments, not a string"):
        LiveAppConfig(command="uvicorn app:app --port {port}")


def test_command_given_as_a_list_is_accepted() -> None:
    config = LiveAppConfig(command=["uvicorn", "app:app"])
    assert list(config.command) == ["uvicorn", "app:app"]


def test_live_app_repr_hides_the_environment_and_config() -> None:
    # A failing ``assert live_app.port == -1`` prints repr(live_app); the process
    # environment (secrets included) must not be in it.
    from regression_kit import LiveApp

    config = LiveAppConfig(command=["x"], env={"SENTINEL_TOKEN": "s3cr3t-value-7f3a"})
    app = LiveApp(
        base_url="http://127.0.0.1:1",
        port=1,
        process=object(),  # type: ignore[arg-type]
        config=config,
        env={"SENTINEL_TOKEN": "s3cr3t-value-7f3a", "HOME": "/h"},
        _reader=object(),  # type: ignore[arg-type]
    )
    shown = repr(app)
    assert "env=" not in shown
    assert "config=" not in shown
    assert "s3cr3t-value-7f3a" not in shown
    assert "port=1" in shown and "base_url=" in shown
