# Changelog

## 0.1.0 — 2026-10-15

Initial release.

- `live_app` session fixture driven by a user-defined `live_app_config` fixture
  returning `LiveAppConfig`: launches the app, allocates and substitutes
  `{port}` or parses the port from the output, polls readiness, tears the
  process group down (SIGTERM, 5 s, SIGKILL).
- `LiveAppStartupError` carrying the reason and the last 200 lines of output.
- `functional` marker (renamable via the `regression_kit_marker` ini option)
  and a browser guard: skip without Chromium, or fail with `--require-browser` /
  `REGRESSION_KIT_REQUIRE_BROWSER=1`.
- Pure helpers: `parse_port`, `free_port`, `merge_env`, `substitute_port`,
  `base_env`, `is_ready`, `browser_available`.

Changes from the adversarial review of the first build (same unreleased version):

- Teardown never blocks on a held pipe: if a process outside the group keeps
  the output pipe open, the reader thread is left behind after 5 s and a
  `RuntimeWarning` names the leak (M1).
- `LiveApp.config` and `LiveApp.env` are excluded from `repr()`, so a failing
  assertion does not print the process environment (M2).
- `LiveAppConfig.inherit_env` (default `True`); `False` passes only `PATH`,
  `HOME`, `LANG`/`LC_*`, `TMPDIR`, `PYTHON*`, `VIRTUAL_ENV`, `UV_*` plus
  `env` (M2).
- CI job and README install Chromium with `uv run playwright install`, the
  Python package's own browser revision (M3).
- `is_ready` treats a non-HTTP listener (`http.client.HTTPException`) as not
  ready; README notes the default port pattern takes the first match (M4).
- `browser_available` understands `PLAYWRIGHT_BROWSERS_PATH=0` and the Windows
  `%LOCALAPPDATA%\ms-playwright` cache; README states `live_app` is
  POSIX-only (M5).
- `browser_available` requires the `INSTALLATION_COMPLETE` marker inside the
  `chromium*` directory (M6).
- `LiveAppConfig(command="...")` raises `TypeError` at construction (M7).
- `is_ready` no longer follows redirects; `ready_status` is compared against
  the first status the server returns (M8).
- README example uses `tmp_path_factory`; the session-scope requirement for
  `live_app_config` is stated (M9, M10).
- Tests pin the SIGKILL fallback, the process-group kill and the `{port}`
  token appearing only in an `env` value.

Added after the review round (same unreleased version):

- The kit's own browser tests, `tests/functional/test_browser.py`: three
  `functional` tests driving `tests/sample_app.py` through `live_app` with
  pytest-playwright's `page`, including a click whose effect only a browser that
  ran the page's JavaScript can observe. Skipped by the guard where Chromium is
  absent; run for real by the CI `browser` job.
- `docs/ci/kit-ci.yml`: CI for the kit itself — a Python 3.11/3.12/3.14 ×
  `pytest>=8,<9`/latest matrix for the browserless suite plus ruff, and a
  `browser` job that installs Chromium and runs `-m functional
  --require-browser`. `docs/ci/functional-tests.yml` remains the job for a
  project that uses the kit.
- `pytest-playwright` as a dev dependency; a test pins that its importability
  alone does not satisfy the browser guard.
- The sample app serves `/page` (a button whose click writes text from JS).
