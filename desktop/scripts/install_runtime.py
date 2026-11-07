#!/usr/bin/env python3
"""Create the local Python runtime used by the Tauri shell.

The runtime is a normal venv under ``desktop/.runtime``. Installing cecli into
it lets the desktop app start both the bridge and the agent from one
interpreter, without requiring cecli on PATH.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "desktop" / ".runtime" / "venv"


def venv_python(target: Path) -> Path:
    """Return the interpreter path for a venv on this platform."""
    if os.name == "nt":
        return target / "Scripts" / "python.exe"
    return target / "bin" / "python"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the desktop Python runtime")
    parser.add_argument("--venv", type=Path, default=RUNTIME, help="target venv directory")
    parser.add_argument(
        "--project",
        type=Path,
        default=ROOT,
        help="cecli project to install (default: repository root)",
    )
    args = parser.parse_args()

    target = args.venv.resolve()
    python = venv_python(target)
    if not python.exists():
        print(f"creating {target}")
        venv.EnvBuilder(with_pip=True, clear=False).create(target)

    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "-e", str(args.project.resolve())],
        check=True,
    )

    print(f"desktop runtime ready: {python}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
