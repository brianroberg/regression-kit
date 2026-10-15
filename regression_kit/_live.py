"""Start, watch and stop the app under test as a subprocess."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from regression_kit._core import (
    PORT_TOKEN,
    free_port,
    is_ready,
    merge_env,
    parse_port,
    substitute_port,
)

OUTPUT_TAIL_LINES = 200
_POLL_INTERVAL = 0.05
_READY_PROBE_TIMEOUT = 1.0
_TERMINATE_GRACE = 5.0


class LiveAppStartupError(RuntimeError):
    """The app under test did not come up; the message carries the reason and output."""


@dataclass(frozen=True)
class LiveAppConfig:
    """How to launch the app under test.

    ``command`` may contain the literal token ``{port}``; if it does (in the
    command or in an ``env`` value) a free port is allocated and substituted in
    both. Otherwise the port is parsed from the process output with
    ``port_pattern`` (None = the default pattern, which understands uvicorn,
    Flask, gunicorn and any ``127.0.0.1:PORT`` / ``localhost:PORT`` /
    ``0.0.0.0:PORT``). ``ready_path`` is polled until it answers with a status in
    ``ready_status`` or ``startup_timeout`` seconds have passed since launch.
    """

    command: Sequence[str]
    ready_path: str = "/"
    ready_status: Collection[int] = range(200, 500)
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: str | Path | None = None
    startup_timeout: float = 30.0
    port_pattern: str | None = None
    host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        if isinstance(self.command, (str, bytes)):
            raise TypeError("command must be a sequence of arguments, not a string")

    def uses_port_token(self) -> bool:
        return any(PORT_TOKEN in arg for arg in self.command) or any(
            PORT_TOKEN in value for value in self.env.values()
        )


class _OutputReader:
    """Drains the process's combined stdout/stderr on a thread, keeping the tail."""

    def __init__(self, process: subprocess.Popen[str], port_pattern: str | None) -> None:
        self._lines: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
        self._lock = threading.Lock()
        self._port_pattern = port_pattern
        self.port: int | None = None
        self.port_seen = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(process.stdout,), name="regression-kit-output", daemon=True
        )
        self._thread.start()

    def _run(self, stream) -> None:
        for raw in stream:
            line = raw.rstrip("\n")
            with self._lock:
                self._lines.append(line)
            if not self.port_seen.is_set():
                port = parse_port(line, self._port_pattern)
                if port is not None:
                    self.port = port
                    self.port_seen.set()
        self.port_seen.set()  # EOF: wake anyone waiting for a port

    def tail(self) -> str:
        with self._lock:
            return "\n".join(self._lines)

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)


@dataclass
class LiveApp:
    """A running app under test, as yielded by the ``live_app`` fixture."""

    base_url: str
    port: int
    process: subprocess.Popen[str]
    config: LiveAppConfig
    env: Mapping[str, str]
    _reader: _OutputReader = field(repr=False)

    def url(self, path: str) -> str:
        return self.base_url + (path if path.startswith("/") else "/" + path)

    def output_tail(self) -> str:
        """The last ~200 lines of the server's combined stdout/stderr."""
        return self._reader.tail()


def _spawn(config: LiveAppConfig, port: int | None) -> tuple[subprocess.Popen[str], dict[str, str]]:
    substituted = port if port is not None else 0
    command = substitute_port(config.command, substituted)
    env = merge_env(os.environ, config.env, substituted)
    process = subprocess.Popen(
        command,
        cwd=str(config.cwd) if config.cwd is not None else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )
    return process, env


def start_live_app(config: LiveAppConfig) -> LiveApp:
    """Launch the app, discover its port, wait until it answers, or raise."""
    __tracebackhide__ = True
    if not isinstance(config, LiveAppConfig):
        raise TypeError(f"expected a LiveAppConfig, got {type(config).__name__}")
    deadline = time.monotonic() + config.startup_timeout
    port = free_port(config.host) if config.uses_port_token() else None
    process, env = _spawn(config, port)
    reader = _OutputReader(process, config.port_pattern)

    def fail(reason: str) -> LiveAppStartupError:
        _stop(process, reader)
        return LiveAppStartupError(
            f"{reason}\n--- server output (last {OUTPUT_TAIL_LINES} lines) ---\n{reader.tail()}"
        )

    if port is None:
        while True:
            if reader.port_seen.wait(_POLL_INTERVAL) and reader.port is not None:
                port = reader.port
                break
            if reader.port_seen.is_set():
                time.sleep(_POLL_INTERVAL)  # output ended without a port; wait for exit/deadline
            code = process.poll()
            if code is not None:
                raise fail(
                    f"app exited with code {code} during startup (command: {config.command})"
                )
            if time.monotonic() > deadline:
                raise fail(
                    f"app did not report a port within {config.startup_timeout}s "
                    f"(command: {config.command}; pattern: {config.port_pattern or 'default'})"
                )

    base_url = f"http://{config.host}:{port}"
    ready_url = base_url + config.ready_path
    while True:
        code = process.poll()
        if code is not None:
            raise fail(
                f"app exited with code {code} before becoming ready (command: {config.command})"
            )
        if is_ready(ready_url, config.ready_status, _READY_PROBE_TIMEOUT):
            break
        if time.monotonic() > deadline:
            raise fail(
                f"app did not answer {ready_url} with a status in {config.ready_status!r} "
                f"within {config.startup_timeout}s"
            )
        time.sleep(_POLL_INTERVAL)

    return LiveApp(
        base_url=base_url, port=port, process=process, config=config, env=env, _reader=reader
    )


def _signal_group(process: subprocess.Popen[str], sig: signal.Signals) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), sig)
        else:  # pragma: no cover - Windows
            process.send_signal(sig)
    except ProcessLookupError:
        pass


def _stop(process: subprocess.Popen[str], reader: _OutputReader) -> None:
    """SIGTERM the process group, wait up to 5 s, then SIGKILL it."""
    if process.poll() is None:
        _signal_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=_TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            _signal_group(process, signal.SIGKILL)
            process.wait()
    reader.join(timeout=_TERMINATE_GRACE)
    if process.stdout is not None:
        process.stdout.close()


def stop_live_app(app: LiveApp) -> None:
    """Terminate the app under test (SIGTERM, 5 s grace, then SIGKILL)."""
    _stop(app.process, app._reader)
