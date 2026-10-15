# regression-kit — working rules

A pytest plugin (`regression_kit`, entry point `pytest11`) that starts an app
under test as a subprocess and guards browser tests. Runtime dependency is
`pytest>=8` only; Python 3.11+.

## Running

```bash
uv sync                               # once; builds .venv
uv run --no-sync pytest -q            # the suite needs no browser
uv run --no-sync pytest -q -n auto    # must also pass in parallel
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
```

## Rules

- **Red/green TDD.** Write the failing test first, see it fail for the right
  reason, write the minimal code, refactor. Put the trimmed red and green output
  in the commit message.
- **Pure logic stays in `regression_kit/_core.py`**, free of pytest and of
  process management, so it is unit- and property-testable. Process handling
  lives in `_live.py`; pytest hooks and fixtures in `plugin.py`.
- **No `.github/workflows/` pushes from the bot account** — its token lacks the
  `workflow` scope. CI content lives in `docs/ci/`; the repo owner copies it in.
- **Keep README claims to what tests pin.** The browser half (a real Playwright
  `page` against `live_app`) is proven on a machine with Chromium or in CI, not
  in this suite; say so rather than imply otherwise.
- Branch + PR only; never push to `main` directly once the repo is transferred.
