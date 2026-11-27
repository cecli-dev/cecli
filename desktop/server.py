"""Launcher for the desktop bridge.

The bridge implementation now lives in ``cecli.helpers.desktop`` and runs inside
the ``cecli --acp`` process, so the desktop needs one Python interpreter instead
of two. Rust still launches this file for packaging compatibility; executing it
replaces the process with ``cecli`` and forwards the old flags. Importing it
keeps ``desktop.server`` working for the existing tests.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _find_cecli(explicit: str | None) -> str:
    if explicit:
        return explicit

    for name in ("CECLI_BIN", "CECLI_DESKTOP_CECLI"):
        value = os.environ.get(name)
        if value:
            return value

    suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).with_name(f"cecli{suffix}")
    if sibling.is_file():
        return str(sibling)

    return shutil.which("cecli") or "cecli"


def bridge_args(argv: list[str]) -> tuple[list[str], str | None]:
    """Translate the old server flags into ``cecli --desktop-bridge`` flags.

    Returns the new argument list and the resolved cecli executable.
    """
    if "--" in argv:
        split = argv.index("--")
        argv, extra = argv[:split], argv[split + 1 :]
    else:
        extra = []

    values = {
        "--host": "127.0.0.1",
        "--port": "8765",
        "--workspace": os.getcwd(),
        "--cecli": None,
        "--token": os.environ.get("CECLI_DESKTOP_TOKEN"),
        "--max-sessions": None,
        "--static-root": str(Path(__file__).resolve().parent),
        "--terminal-shell": os.environ.get("CECLI_DESKTOP_TERMINAL_SHELL"),
    }
    booleans = {"--open": False, "--no-terminal": False}
    passthrough: list[str] = []

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in values:
            index += 1
            if index >= len(argv):
                raise SystemExit(f"{arg} requires a value")
            values[arg] = argv[index]
        elif arg in booleans:
            booleans[arg] = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            raise SystemExit(0)
        else:
            passthrough.append(arg)
        index += 1

    cecli = _find_cecli(values["--cecli"])
    workspace = os.path.abspath(os.path.expanduser(str(values["--workspace"])))
    static_root = os.path.abspath(os.path.expanduser(str(values["--static-root"])))

    translated = [
        "--acp",
        "--desktop-bridge",
        "--desktop-bridge-host",
        str(values["--host"]),
        "--desktop-bridge-port",
        str(values["--port"]),
        "--desktop-bridge-workspace",
        workspace,
        "--desktop-bridge-static-root",
        static_root,
    ]

    if values["--token"]:
        translated.extend(["--desktop-bridge-token", str(values["--token"])])
    if values["--max-sessions"]:
        translated.extend(["--desktop-bridge-max-sessions", str(values["--max-sessions"])])
    if values["--terminal-shell"]:
        translated.extend(["--desktop-bridge-terminal-shell", str(values["--terminal-shell"])])
    if booleans["--open"]:
        translated.append("--desktop-bridge-open")
    if booleans["--no-terminal"]:
        translated.append("--desktop-bridge-no-terminal")

    translated.extend(passthrough)
    if extra:
        translated.append("--")
        translated.extend(extra)

    return translated, cecli


def main(argv: list[str] | None = None) -> int:
    """Run the bridge in-process, or replace this process with a hosting cecli."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--desktop-bridge" not in args:
        from cecli.helpers.desktop.bridge import main as bridge_main

        if "--static-root" not in args:
            args.extend(["--static-root", str(Path(__file__).resolve().parent)])
        return bridge_main(args)

    translated, cecli = bridge_args([arg for arg in args if arg != "--desktop-bridge"])
    try:
        os.execv(cecli, [cecli, *translated])
    except OSError as error:
        print(f"could not start {cecli}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Import compatibility for the existing desktop tests.
from cecli.helpers.desktop import bridge as _impl  # noqa: E402

for _name, _value in vars(_impl).items():
    if not _name.startswith("__") and _name not in globals():
        globals()[_name] = _value

sys.modules[__name__] = _impl
