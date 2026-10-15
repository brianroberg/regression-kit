# regression-kit

A pytest plugin that gives every web project the same way to run browser/e2e
regression tests against a **live, seeded, never-production** copy of the app.

It replaces the hand-rolled "launch uvicorn, find the port, poll until ready"
fixture that each project otherwise grows on its own. The plugin provides:

- a session-scoped `live_app` fixture that starts your app as a subprocess,
  discovers its port, waits until it answers HTTP, and tears it down;
- a `functional` marker plus a browser guard: marked tests are skipped when
  Playwright's Chromium is not installed, and **fail** instead when you pass
  `--require-browser` (so CI can never go green because the browser was missing);
- small pure helpers (`parse_port`, `merge_env`, `browser_available`, …) you can
  reuse directly.

Runtime dependency: `pytest>=8` only. Python 3.11+. Browser tests additionally
need `pytest-playwright` and a Chromium install, which this plugin does not
install: run `uv run playwright install --with-deps chromium` (the Python
package's own browser revision — installing through the npm CLI instead fetches npm's
revision, which is usually a different one, so the guard would find a browser
directory and the launch would still fail). **The `live_app` fixture is POSIX-only** (Linux, macOS): it relies on
process groups and POSIX signals to tear the app down. The marker and browser
guard work anywhere.

## Install

```bash
uv add --dev "regression-kit @ git+https://github.com/brianroberg/regression-kit"
```

The repository is being transferred to `brianroberg`; until the transfer lands,
the URL is `https://github.com/brianroberg-agent/regression-kit`. The plugin
registers itself through the `pytest11` entry point; nothing to add to `conftest.py`
except your own `live_app_config` fixture.

## Usage

```python
# tests/conftest.py
import pytest
from regression_kit import LiveAppConfig

from tests.seed import seed_database  # your project's seed function


@pytest.fixture(scope="session")  # must be session-scoped, see below
def live_app_config(tmp_path_factory):
    db = tmp_path_factory.mktemp("regression-kit") / "app.db"
    seed_database(f"sqlite:///{db}")  # one row per UI state, fictional data only
    return LiveAppConfig(
        command=["uv", "run", "uvicorn", "app.main:app", "--port", "{port}"],
        ready_path="/docs",
        env={"DATABASE_URL": f"sqlite:///{db}"},
        inherit_env=False,  # the app sees only what is set here, never your shell
    )


# tests/test_functional.py
import pytest


@pytest.mark.functional
def test_dashboard_lists_seeded_rows(live_app, page):  # ``page`` is pytest-playwright's
    page.goto(live_app.url("/dashboard"))
    assert page.get_by_text("Avery Anderson").is_visible()
```

Run the browser tests with `uv run pytest -m functional`; run everything else
with `-m "not functional"`.

`live_app_config` **must be session-scoped**: `live_app` is a session fixture,
and pytest refuses to let a session fixture depend on a function-scoped one
(`ScopeMismatch: You tried to access the function scoped fixture
live_app_config with a session scoped request object`). The example uses
`tmp_path_factory` rather than `tmp_path` for the same reason.

### `LiveAppConfig`

| field | default | meaning |
|---|---|---|
| `command` | required | argv to launch the app. If it (or an `env` value) contains the literal token `{port}`, a free port is allocated and substituted; otherwise the port is **parsed from the process output**. |
| `ready_path` | `"/"` | path polled until the app answers. A port that accepts the connection but does not answer HTTP counts as not ready |
| `ready_status` | `range(200, 500)` | any status in this collection means "up" — a 401 or 404 on `/login` still proves the server answers. The status compared is the **first** one the server returns: redirects are **not** followed, so a `/` that answers `302 → /login` is ready with the default (302 is in range) and a custom `ready_status={200}` would need `ready_path="/login"` |
| `env` | `{}` | merged over the inherited environment (see `inherit_env`); `{port}` is substituted in values |
| `inherit_env` | `True` | pass the parent's whole environment to the app. With `False` the app receives **only** `PATH`, `HOME`, `LANG`/`LC_*`, `TMPDIR`, `PYTHON*`, `VIRTUAL_ENV` and `UV_*` from the parent, plus `env` |
| `cwd` | `None` | working directory for the process |
| `startup_timeout` | `30.0` | seconds allowed for port discovery **and** readiness together |
| `port_pattern` | `None` | regex with one group; the default understands uvicorn (`Uvicorn running on http://127.0.0.1:PORT`), Flask (`Running on http://127.0.0.1:PORT`), gunicorn (`Listening at: http://127.0.0.1:PORT`) and any bare `127.0.0.1:PORT` / `localhost:PORT` / `0.0.0.0:PORT`. The **first** matching output line wins, so an app that logs some other local port first (a database, a debugger, a metrics endpoint) needs a `port_pattern` that matches only its HTTP listener |
| `host` | `"127.0.0.1"` | host used for the free port and the base URL |

### `LiveApp` (what `live_app` yields)

`base_url`, `port`, `process` (the `subprocess.Popen`), `config`, `env` (the
environment the process was given), `url(path)` and `output_tail()` — the last
200 lines of the server's combined stdout/stderr, which is also included in
every `LiveAppStartupError`. `config` and `env` are excluded from `repr(live_app)`,
so a failing assertion that prints the fixture does not print your secrets.

Startup failures (the process exits early, never prints a port, or never answers
`ready_path` within `startup_timeout`) raise `LiveAppStartupError` with the
reason and the output tail. Teardown sends SIGTERM to the process group, waits
5 s, then SIGKILL. If a process **outside** that group (one the app started in
its own session) still holds the app's output pipe, teardown does not wait for
it: after a further 5 s it leaves the reader thread behind and emits a
`RuntimeWarning` naming the leak, so the session still ends. If
`live_app_config` is not defined, `live_app` fails with a message naming it.

### Marker and browser guard

`pytest_configure` registers the marker `functional` (rename it with the ini
option `regression_kit_marker`). At collection time the plugin checks whether a
browser is available: the `playwright` package must be importable **and** a
directory starting with `chromium` holding Playwright's `INSTALLATION_COMPLETE`
marker (a directory without it is an interrupted download) must exist under
`PLAYWRIGHT_BROWSERS_PATH` (if set; the special value `0` means inside the
`playwright` package, as Playwright documents), else `~/.cache/ms-playwright`
on Linux, `~/Library/Caches/ms-playwright` on macOS or
`%LOCALAPPDATA%\ms-playwright` on Windows.

| browser available | default | `--require-browser` or `REGRESSION_KIT_REQUIRE_BROWSER=1` |
|---|---|---|
| yes | marked tests run untouched | marked tests run untouched |
| no | marked tests are **skipped** with the reason | marked tests **error at setup** with the reason; the run is red |

The failure is raised before any fixture runs, so a missing browser is reported
as a setup ERROR naming the cause, not as a Playwright launch traceback. Tests
without the marker are never touched.

### The seed convention

Each project owns one function that writes **one row per UI state** into a
throwaway database **before** the server starts (call it from
`live_app_config`, as above). Use fictional data only. Never point `live_app` at
a production or shared database; the point of the fixture is that the app under
test is a disposable copy.

**Set `DATABASE_URL` (or whatever your app reads) explicitly in `env`, or pass
`inherit_env=False`.** The default inherits the developer's shell, so a
`DATABASE_URL` exported there for day-to-day work would silently point the
"seeded copy" at production. With `inherit_env=False` only the variables the
interpreter and tooling need come through; everything the app needs must be
in `env`.

## What is proven where

The plugin's own suite (`uv run pytest`) runs without a browser: it drives a
stdlib HTTP server through `live_app` three ways (port token in the command,
token only in an `env` value, and parsed port), exercises every startup failure
path, pins the teardown claims (SIGKILL after a server ignores SIGTERM, the
in-group child dies with it, a grandchild holding the pipe cannot hang the
session), and tests the browser guard with `browser_available` monkeypatched
to both outcomes — and, with `pytest-playwright` installed as a dev dependency,
that an importable `playwright` package alone does not make the guard say yes.

The Playwright half — that a marked test using `page` actually runs against
`live_app` — lives in `tests/functional/test_browser.py`: three functional
tests against the sample app, one of which clicks a button and asserts the text
its JavaScript wrote, which no plain HTTP client can see. On a machine without
Chromium (such as the one this was developed on) they are **skipped by the
kit's own guard**; they run for real in the kit's CI `browser` job
(`docs/ci/kit-ci.yml`) once the repo owner installs that workflow. Until that
job has run green, the browser path is written and guarded but not yet proven.

### The two CI files

| file | for whom | what it runs |
|---|---|---|
| `docs/ci/kit-ci.yml` | **this repository** | `tests`: the browserless suite over Python 3.11/3.12/3.14 × `pytest>=8,<9`/latest, plus ruff; `browser`: `tests/functional/` in real Chromium with `--require-browser` |
| `docs/ci/functional-tests.yml` | **a project that uses the kit** | that project's own `-m functional` tests with `--require-browser`; copy it and adjust the Python version and test path |

Both live under `docs/ci/` because the bot account that writes this repo cannot
push to `.github/workflows/`; the owner copies them in from a credential with
the `workflow` scope.

## Developing

```bash
uv sync
uv run --no-sync pytest -q            # or: -n auto
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
uv run playwright install --with-deps chromium   # optional: makes tests/functional/ run for real
```

The pytester-based tests pass `-p no:playwright` to their inner runs
(`tests/conftest.py`): pytest-playwright wraps every test call in a
soft-assertion scope that cannot nest, so an in-process inner pytest would
otherwise fail every test with "nested soft assertion scopes are not supported".

See `CLAUDE.md` for the working rules (TDD, no workflow pushes from the bot).
