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


def test_readme_example_uses_pytests_own_temp_factory() -> None:
    # tmp_path_factory is session-usable, cleaned up by pytest, and shows the
    # fixture must be session-scoped; tempfile.mkdtemp leaks a directory per run.
    assert "tmp_path_factory.mktemp(" in README
    assert "tempfile.mkdtemp" not in README


def test_readme_says_live_app_config_must_be_session_scoped() -> None:
    assert "ScopeMismatch" in README
