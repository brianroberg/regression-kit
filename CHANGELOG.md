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
  `is_ready`, `browser_available`.
