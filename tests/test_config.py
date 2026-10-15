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
