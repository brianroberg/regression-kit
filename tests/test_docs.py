"""Pins on documentation claims that are easy to regress and are not exercised by code."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
CI_JOB = (ROOT / "docs" / "ci" / "functional-tests.yml").read_text()


def test_ci_job_installs_chromium_through_the_python_package() -> None:
    # npm's playwright pins a different browser revision than the Python package;
    # with ``npx`` the guard would find a chromium dir and launch would then fail.
    assert "uv run playwright install --with-deps chromium" in CI_JOB
    assert "npx playwright install" not in CI_JOB
    assert "npx playwright install" not in README
