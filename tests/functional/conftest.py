"""The kit's own browser tests run tests/sample_app.py through ``live_app``."""

from __future__ import annotations

from pathlib import Path

import pytest

from regression_kit import LiveAppConfig

SAMPLE_APP = Path(__file__).resolve().parents[1] / "sample_app.py"


@pytest.fixture(scope="session")
def live_app_config() -> LiveAppConfig:
    import sys

    return LiveAppConfig(
        command=[sys.executable, str(SAMPLE_APP), "{port}"],
        ready_path="/health",
        ready_status={200},
        inherit_env=False,
        startup_timeout=20,
    )
