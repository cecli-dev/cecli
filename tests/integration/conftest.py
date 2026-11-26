"""Shared fixtures for the cross-platform app-harness acceptance suite.

The integration suite has two halves:

* Protocol and CLI-contract tests run against an isolated fake bridge and are
  hermetic. They never touch a real desktop and run by default.
* Platform acceptance tests (Windows UIA, Linux AT-SPI) need a real bridge and
  are gated behind ``CECLI_INTEGRATION=1``.

The fake bridge starts from the first available source, in order:

1. a compiled Rust test server (``target/debug/examples/fake_bridge``),
2. the signed ``ce-underscore`` binary in ``--app-harness`` mode with
   ``CECLI_BRIDGE_BACKEND=fake``,
3. the in-process Python fake from ``tests/app_harness/conftest.py``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pytest

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BRIDGE_START_TIMEOUT_SECONDS = 15.0


def pytest_configure(config: pytest.Config) -> None:
    """Register suite-specific markers without editing ``pytest.ini``."""

    config.addinivalue_line(
        "markers", "windows: Windows UIA acceptance checks (requires a real bridge)"
    )
    config.addinivalue_line(
        "markers", "linux: Linux AT-SPI acceptance checks (requires a session bus)"
    )
    config.addinivalue_line("markers", "integration: end-to-end bridge checks")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Repository root that contains the ``cecli`` package and ``venv``."""

    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def cli_python(repo_root: Path) -> str:
    """Interpreter that can import ``cecli.helpers.app_harness.cli``."""

    for relative in ("venv/bin/python", "venv/Scripts/python.exe"):
        candidate = repo_root / relative

        if candidate.exists():
            return str(candidate)

    return sys.executable


@pytest.fixture(scope="session")
def cli(repo_root: Path, cli_python: str) -> "CliRunner":
    """Subprocess runner for the installed ``app-harness`` entry point."""

    probe = subprocess.run(
        [cli_python, "-c", "import cecli.helpers.app_harness.cli"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
    )

    if probe.returncode != 0:
        pytest.skip(f"cecli.helpers.app_harness.cli is not importable: {probe.stderr.strip()}")

    return CliRunner(python=cli_python, repo_root=repo_root)


@pytest.fixture(scope="session")
def integration_enabled() -> bool:
    """True when the operator opted into host-desktop acceptance tests."""

    return os.environ.get("CECLI_INTEGRATION") == "1"


@pytest.fixture()
def fake_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_root: Path
) -> Iterator["BridgeHandle"]:
    """Start an isolated fake bridge and point discovery at it."""

    handle = start_isolated_bridge(tmp_path=tmp_path, repo_root=repo_root)

    for name in (
        "CECLI_BRIDGE_VERSION_SKIP",
        "CECLI_APP_TIMEOUT_MS",
        "CECLI_CE_UNDERSCORE",
        "CECLI_BRIDGE_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(handle.bridge_path))

    try:
        yield handle
    finally:
        handle.stop()


@pytest.fixture()
def real_bridge(integration_enabled: bool) -> Iterator["BridgeHandle"]:
    """Attach to the bridge named by ``CECLI_BRIDGE_FILE`` or skip clearly."""

    if not integration_enabled:
        pytest.skip("set CECLI_INTEGRATION=1 to run host-desktop acceptance tests")

    handle = discover_real_bridge()

    if handle is None:
        pytest.skip(
            "no real bridge: set CECLI_BRIDGE_FILE to bridge.json written by "
            "ce-underscore --app-harness"
        )

    yield handle


@dataclass
class CliResult:
    """Captured outcome of one ``app-harness`` invocation."""

    argv: Sequence[str]
    returncode: int
    stdout: str
    stderr: str
    duration: float

    def json(self) -> Any:
        """Decode stdout as JSON, failing with the raw text when invalid."""

        try:
            return json.loads(self.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"stdout is not JSON for {self.argv}: {self.stdout!r}") from exc


@dataclass
class CliRunner:
    """Run ``python -m cecli.helpers.app_harness.cli`` with a clean environment."""

    python: str
    repo_root: Path

    def run(
        self,
        *args: str,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float = 90.0,
    ) -> CliResult:
        """Run the CLI and capture output without raising on non-zero exits."""

        merged_env = os.environ.copy()
        merged_env.pop("CECLI_BRIDGE_VERSION_SKIP", None)
        merged_env.pop("CECLI_APP_TIMEOUT_MS", None)
        merged_env["PYTHONPATH"] = str(self.repo_root)

        if env:
            merged_env.update(env)

        started = time.monotonic()
        completed = subprocess.run(
            [self.python, "-m", "cecli.helpers.app_harness.cli", *args],
            cwd=str(self.repo_root),
            env=merged_env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CliResult(
            argv=args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration=time.monotonic() - started,
        )


@dataclass
class BridgeHandle:
    """A running bridge process or in-process fake plus its discovery file."""

    kind: str
    directory: Path
    bridge_path: Path
    port: int
    token: str
    process: subprocess.Popen[Any] | None = None
    fake: Any = None
    log_path: Path | None = None

    @property
    def is_python_fake(self) -> bool:
        """True when the in-process Python fake is serving this handle."""

        return self.kind == "python"

    @property
    def is_rust(self) -> bool:
        """True when a compiled Rust server is serving this handle."""

        return self.kind in {"rust", "ce-underscore"}

    def env(self, **overrides: str) -> dict[str, str]:
        """Environment overrides that point the CLI at this bridge."""

        environment = {"CECLI_BRIDGE_FILE": str(self.bridge_path)}
        environment.update(overrides)
        return environment

    def bridge_json(self) -> dict[str, Any]:
        """Decode the current ``bridge.json``."""

        return json.loads(self.bridge_path.read_text(encoding="utf-8"))

    def write_version(self, version: str) -> None:
        """Rewrite the version field, used by mismatch tests."""

        payload = self.bridge_json()
        payload["version"] = version
        self.bridge_path.write_text(json.dumps(payload), encoding="utf-8")

    def request_paths(self) -> list[str]:
        """Paths received by the fake, or an empty list for native servers."""

        if self.fake is None:
            return []

        return list(self.fake.paths())

    def set_action_mode(self, mode: str) -> None:
        """Select the Python fake action mode; ignored by native servers."""

        if self.fake is not None:
            self.fake.action_mode = mode

    def stop(self) -> None:
        """Stop owned processes; leave a discovery-only bridge untouched."""

        if self.fake is not None:
            try:
                self.fake.stop()
            except OSError:
                pass

            self.fake = None
            return

        if self.process is None:
            return

        if self.process.poll() is None:
            self.process.terminate()

            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

        self.process = None


def start_isolated_bridge(tmp_path: Path, repo_root: Path) -> BridgeHandle:
    """Start a fake bridge, preferring compiled servers over Python."""

    bridge_path = tmp_path / "bridge.json"

    for binary in _rust_fake_candidates(repo_root):
        handle = _spawn_bridge_kind(
            binary=binary,
            arguments=[],
            kind="rust",
            directory=tmp_path,
            bridge_path=bridge_path,
            expected_prefix="",
        )

        if handle is not None:
            return handle

    ce_underscore = _find_ce_underscore(repo_root)

    if ce_underscore is not None:
        handle = _spawn_bridge_kind(
            binary=ce_underscore,
            arguments=["--app-harness"],
            kind="ce-underscore",
            directory=tmp_path,
            bridge_path=bridge_path,
            expected_prefix="",
            extra_env={"CECLI_BRIDGE_BACKEND": "fake"},
        )

        if handle is not None:
            return handle

    return _start_python_fake(tmp_path, repo_root)


def discover_real_bridge() -> BridgeHandle | None:
    """Return a read-only handle for ``CECLI_BRIDGE_FILE`` when it answers."""

    override = os.environ.get("CECLI_BRIDGE_FILE")

    if not override:
        return None

    bridge_path = Path(override).expanduser()

    if not bridge_path.exists():
        return None

    try:
        payload = json.loads(bridge_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    port = int(payload.get("port") or 0)
    token = str(payload.get("token") or "")

    if port <= 0 or not token:
        return None

    if not _state_responds(str(payload.get("host") or "127.0.0.1"), port, token):
        return None

    return BridgeHandle(
        kind="real",
        directory=bridge_path.parent,
        bridge_path=bridge_path,
        port=port,
        token=token,
    )


def _rust_fake_candidates(repo_root: Path) -> list[Path]:
    candidates = [
        repo_root / "target/debug/examples/fake_bridge",
        repo_root / "desktop/target/debug/examples/fake_bridge",
        repo_root / "desktop/app-bridge/target/debug/examples/fake_bridge",
        repo_root / "target/debug/fake_bridge",
        repo_root / "target/debug/fake_bridge.exe",
        repo_root / "desktop/target/debug/examples/fake_bridge.exe",
    ]

    return [candidate for candidate in candidates if candidate.exists()]


def _find_ce_underscore(repo_root: Path) -> Path | None:
    """Return a ``ce-underscore`` that actually supports ``--app-harness``.

    Stale debug builds of the desktop binary exist in some checkouts and do not
    parse the bridge flag. Probe ``--help`` so a wrong binary falls back to the
    Python fake instead of starting a GUI for 15 seconds.
    """

    override = os.environ.get("CECLI_CE_UNDERSCORE")

    if override:
        candidate = Path(override).expanduser()

        if candidate.exists() and _supports_app_harness(candidate):
            return candidate

    candidates = [
        repo_root / "target/debug/ce-underscore",
        repo_root / "target/debug/ce-underscore.exe",
        repo_root / "desktop/src-tauri/target/debug/ce-underscore",
        repo_root / "desktop/src-tauri/target/debug/ce-underscore.exe",
    ]

    for candidate in candidates:
        if candidate.exists() and _supports_app_harness(candidate):
            return candidate

    found = shutil.which("ce-underscore")

    if found and _supports_app_harness(Path(found)):
        return Path(found)

    return None


def _supports_app_harness(binary: Path, timeout: float = 10.0) -> bool:
    """True when ``binary --help`` advertises the app-harness bridge mode."""

    environment = os.environ.copy()
    environment["CECLI_TUI"] = "false"

    try:
        completed = subprocess.run(
            [str(binary), "--help"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    output = (completed.stdout or "") + (completed.stderr or "")
    return "--app-harness" in output


def _spawn_bridge_kind(
    binary: Path,
    arguments: list[str],
    kind: str,
    directory: Path,
    bridge_path: Path,
    expected_prefix: str,
    extra_env: Mapping[str, str] | None = None,
) -> BridgeHandle | None:
    """Spawn a native bridge and wait for ``bridge.json``; ``None`` on failure."""

    if bridge_path.exists():
        bridge_path.unlink()

    environment = os.environ.copy()
    environment["CECLI_BRIDGE_FILE"] = str(bridge_path)
    environment.setdefault("CECLI_BRIDGE_BACKEND", "fake")

    if extra_env:
        environment.update(extra_env)

    log_path = directory / f"{kind}.log"

    with log_path.open("w", encoding="utf-8") as log_file:
        try:
            process = subprocess.Popen(
                [str(binary), *arguments],
                cwd=str(directory),
                env=environment,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError:
            return None

    payload = _wait_for_bridge_file(process, bridge_path)

    if payload is None:
        _terminate(process)
        return None

    port = int(payload.get("port") or 0)
    token = str(payload.get("token") or "")

    if port <= 0 or not token or not _state_responds("127.0.0.1", port, token):
        _terminate(process)
        return None

    if expected_prefix and not str(payload.get("version", "")).startswith(expected_prefix):
        _terminate(process)
        return None

    return BridgeHandle(
        kind=kind,
        directory=directory,
        bridge_path=bridge_path,
        port=port,
        token=token,
        process=process,
        log_path=log_path,
    )


def _start_python_fake(directory: Path, repo_root: Path) -> BridgeHandle:
    """Load ``tests/app_harness/conftest.py`` and start its fake in-process."""

    module_path = repo_root / "tests" / "app_harness" / "conftest.py"
    spec = importlib.util.spec_from_file_location("integration_python_fake", module_path)

    if spec is None or spec.loader is None:
        pytest.skip(f"cannot load the Python fake bridge from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = module.FakeBridge(directory)
    fake.start()

    if not _state_responds("127.0.0.1", fake.port, fake.token):
        fake.stop()
        pytest.skip("the Python fake bridge did not answer /api/app/state")

    return BridgeHandle(
        kind="python",
        directory=directory,
        bridge_path=fake.bridge_path,
        port=fake.port,
        token=fake.token,
        fake=fake,
    )


def _wait_for_bridge_file(
    process: subprocess.Popen[Any], bridge_path: Path
) -> dict[str, Any] | None:
    deadline = time.monotonic() + BRIDGE_START_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if process.poll() is not None:
            return None

        if bridge_path.exists():
            try:
                payload = json.loads(bridge_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None

            if isinstance(payload, dict) and int(payload.get("port") or 0) > 0:
                return payload

        time.sleep(0.1)

    return None


def _state_responds(host: str, port: int, token: str, timeout: float = 1.0) -> bool:
    request = urllib.request.Request(
        f"http://{host}:{port}/api/app/state",
        method="GET",
        headers={"X-Cecli-Token": token, "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        return False

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False

    return isinstance(payload, dict) and bool(payload.get("ok"))


def _terminate(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
