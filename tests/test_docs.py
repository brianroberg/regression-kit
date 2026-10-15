"""Pins on documentation claims that are easy to regress and are not exercised by code."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
CI_JOB = (ROOT / "docs" / "ci" / "functional-tests.yml").read_text()
KIT_CI = ROOT / "docs" / "ci" / "kit-ci.yml"


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


def test_kit_ci_tests_the_kit_across_python_and_pytest_versions() -> None:
    # The kit's own CI (copied into .github/workflows/ by the repo owner): a matrix
    # over Python x pytest for the browserless suite, plus a browser job that runs
    # the functional tests with --require-browser so a missing Chromium is red.
    text = KIT_CI.read_text()
    for version in ('"3.11"', '"3.12"', '"3.14"'):
        assert version in text
    assert "pytest>=8,<9" in text
    assert '-m "not functional"' in text
    assert "--require-browser" in text
    assert "uv run playwright install --with-deps chromium" in text
    assert "npx" not in text
    assert "ruff check" in text and "ruff format --check" in text
    assert "uv sync --locked" in text
    assert "ms-playwright" in text and "hashFiles('uv.lock')" in text


def test_readme_distinguishes_the_two_ci_files() -> None:
    assert "docs/ci/kit-ci.yml" in README
    assert "docs/ci/functional-tests.yml" in README
