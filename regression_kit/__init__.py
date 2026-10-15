"""regression-kit: live-app fixtures and a browser guard for pytest."""

from regression_kit._core import browser_available
from regression_kit._live import LiveApp, LiveAppConfig, LiveAppStartupError

__version__ = "0.1.0"

__all__ = ["LiveApp", "LiveAppConfig", "LiveAppStartupError", "browser_available"]
