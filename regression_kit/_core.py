"""Pure helpers behind the ``live_app`` fixture and the browser guard.

Everything here is free of pytest and of process management so it can be unit
tested directly. ``plugin.py`` wires these into fixtures and hooks.
"""

from __future__ import annotations

import http.client
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from collections.abc import Collection, Mapping, Sequence
from importlib.util import find_spec
from pathlib import Path

PORT_TOKEN = "{port}"
INSTALL_MARKER = "INSTALLATION_COMPLETE"

# Matches the startup lines of uvicorn ("Uvicorn running on http://127.0.0.1:8000"),
# Flask ("Running on http://127.0.0.1:5000"), gunicorn ("Listening at: http://127.0.0.1:8000")
# and any bare "127.0.0.1:PORT" / "localhost:PORT" / "0.0.0.0:PORT". The trailing
# lookahead stops a longer digit run from being read as a port.
DEFAULT_PORT_PATTERN = r"(?:127\.0\.0\.1|localhost|0\.0\.0\.0):([0-9]{1,5})(?![0-9])"


def parse_port(line: str, pattern: str | None) -> int | None:
    """Return the TCP port named in ``line``, or None if it names none.

    ``pattern`` is a regex with one capturing group; None selects
    :data:`DEFAULT_PORT_PATTERN`. Values outside 1–65535 are rejected.
    """
    match = re.search(pattern or DEFAULT_PORT_PATTERN, line)
    if match is None:
        return None
    try:
        port = int(match.group(1))
    except (ValueError, IndexError):
        return None
    return port if 1 <= port <= 65535 else None


def free_port(host: str) -> int:
    """Ask the OS for a currently free TCP port on ``host`` and return it.

    The port is released before returning, so another process could grab it
    in between; the window is tiny and the server's own bind failure surfaces
    in its output if it happens.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def substitute_port(command: Sequence[str], port: int) -> list[str]:
    """Return ``command`` as a list with every ``{port}`` token replaced."""
    return [arg.replace(PORT_TOKEN, str(port)) for arg in command]


# Variables a child process needs to find its interpreter, its tools and a
# writable temp dir when the parent's environment is NOT inherited. Everything
# else (DATABASE_URL, cloud credentials, ...) must come from ``LiveAppConfig.env``.
_MINIMAL_ENV_KEYS = ("PATH", "HOME", "LANG", "TMPDIR", "VIRTUAL_ENV")
_MINIMAL_ENV_PREFIXES = ("LC_", "PYTHON", "UV_")


def base_env(parent: Mapping[str, str], inherit: bool) -> dict[str, str]:
    """The environment the child starts from, before ``LiveAppConfig.env`` is overlaid.

    With ``inherit=True`` it is a copy of ``parent``. With ``inherit=False`` only
    ``PATH``, ``HOME``, ``LANG``, ``LC_*``, ``TMPDIR``, ``PYTHON*``, ``VIRTUAL_ENV``
    and ``UV_*`` survive, so a ``DATABASE_URL`` sitting in the developer's shell
    cannot silently reach the app under test.
    """
    if inherit:
        return dict(parent)
    return {
        key: value
        for key, value in parent.items()
        if key in _MINIMAL_ENV_KEYS or key.startswith(_MINIMAL_ENV_PREFIXES)
    }


def merge_env(base: Mapping[str, str], extra: Mapping[str, str], port: int) -> dict[str, str]:
    """Overlay ``extra`` on ``base`` and substitute ``{port}`` in ``extra``'s values.

    Every key in ``extra`` wins; keys only in ``base`` survive untouched. Keys are
    never rewritten. A new dict is returned; neither input is modified.
    """
    merged = dict(base)
    for key, value in extra.items():
        merged[key] = value.replace(PORT_TOKEN, str(port))
    return merged


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface a 3xx as the answer instead of following it (possibly off-host)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def is_ready(url: str, statuses: Collection[int], timeout: float) -> bool:
    """True if a GET on ``url`` answers with a status in ``statuses``.

    The status compared is the FIRST one the server returns; redirects are not
    followed, so a 302 on ``/`` is an answer in its own right. Any transport
    failure (refused, reset, timeout) is False, as is a listener that does not
    speak HTTP (``http.client.HTTPException``, e.g. BadStatusLine). An HTTP error
    status is still an answer, so 401/404 count when they are in ``statuses``.
    """
    request = urllib.request.Request(url, method="GET")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (OSError, ValueError, http.client.HTTPException):
        return False
    return status in statuses


def _package_dir(spec: object) -> Path:
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        return Path(next(iter(locations)))
    return Path(str(getattr(spec, "origin", ""))).parent


def _browsers_dir(spec: object) -> Path:
    """Where Playwright keeps its browsers, mirroring its own registry lookup."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override == "0":  # "inside the package", Playwright's documented special value
        return _package_dir(spec) / "driver" / "package" / ".local-browsers"
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def browser_available() -> tuple[bool, str]:
    """Report whether Playwright and a Chromium install are both present.

    Returns ``(ok, reason)``. The reason names what is missing, or the
    Chromium directory that was found. A ``chromium*`` directory counts only
    when it holds Playwright's ``INSTALLATION_COMPLETE`` marker; an interrupted
    download leaves the directory without it and Playwright refuses to launch.
    """
    spec = find_spec("playwright")
    if spec is None:
        return False, "playwright is not installed (pip/uv add pytest-playwright)"
    browsers = _browsers_dir(spec)
    incomplete: list[Path] = []
    if browsers.is_dir():
        for entry in sorted(browsers.iterdir()):
            if entry.is_dir() and entry.name.startswith("chromium"):
                if (entry / INSTALL_MARKER).is_file():
                    return True, f"found {entry}"
                incomplete.append(entry)
    if incomplete:
        return False, (
            f"incomplete chromium install at {incomplete[0]} (no {INSTALL_MARKER} marker; "
            "re-run: playwright install chromium)"
        )
    return False, f"no chromium install under {browsers} (run: playwright install chromium)"
