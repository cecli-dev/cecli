#!/usr/bin/env python3
"""Download the static uv binary and stage it for Tauri's ``externalBin``.

The desktop app ships uv instead of a frozen Python tree: on first launch the
Rust shell asks uv to provide CPython 3.12 and install cecli into a writable
runtime directory, which keeps the installer small.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

desktop = Path(__file__).resolve().parents[1]
binaries = desktop / "src-tauri" / "binaries"

latest_url = "https://github.com/astral-sh/uv/releases/latest/download"
release_url = "https://github.com/astral-sh/uv/releases/download"

uv_targets = {
    "x86_64-unknown-linux-gnu": "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu": "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-musl": "x86_64-unknown-linux-musl",
    "aarch64-unknown-linux-musl": "aarch64-unknown-linux-musl",
    "x86_64-apple-darwin": "x86_64-apple-darwin",
    "aarch64-apple-darwin": "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc": "x86_64-pc-windows-msvc",
    "aarch64-pc-windows-msvc": "aarch64-pc-windows-msvc",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage the uv sidecar")
    parser.add_argument("--triple", default=None, help="target triple (defaults to the Rust host)")
    parser.add_argument(
        "--version", default="latest", help="uv release tag, for example 0.13.7 (default: latest)"
    )
    args = parser.parse_args(argv)

    triple = args.triple or host_triple()
    asset = uv_targets.get(triple)

    if asset is None:
        print(f"no uv build for {triple}", file=sys.stderr)
        return 2

    windows = triple.endswith("windows-msvc")
    archive = f"uv-{asset}.zip" if windows else f"uv-{asset}.tar.gz"
    base = latest_url if args.version == "latest" else f"{release_url}/{args.version}"
    url = f"{base}/{archive}"

    binaries.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if windows else ""
    target = binaries / f"uv-{triple}{suffix}"

    print(f"downloading {url}", flush=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        download = Path(temp_dir) / archive
        fetch(url, download)
        binary = extract(download, f"uv{suffix}", temp_dir)
        shutil.copy2(binary, target)

    if suffix == "":
        target.chmod(target.stat().st_mode | 0o111)

    size = target.stat().st_size / (1024 * 1024)
    print(f"{target.name}: {size:.1f} MiB")
    return 0


def fetch(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "cecli-desktop-build"})

    with urllib.request.urlopen(request) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def extract(archive: Path, name: str, temp_dir: str) -> Path:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            member = next(item for item in bundle.namelist() if item.endswith(f"/{name}"))
            bundle.extract(member, temp_dir)
            return Path(temp_dir) / member

    with tarfile.open(archive) as bundle:
        member = next(item for item in bundle.getmembers() if item.name.endswith(f"/{name}"))
        bundle.extract(member, temp_dir, filter="data")
        return Path(temp_dir) / member.name


def host_triple() -> str:
    # Older rustc releases predate --print host-tuple.
    probe = subprocess.run(["rustc", "--print", "host-tuple"], capture_output=True, text=True)

    if probe.returncode == 0 and probe.stdout.strip():
        return probe.stdout.strip()

    verbose = subprocess.run(["rustc", "-Vv"], capture_output=True, text=True, check=True)

    for line in verbose.stdout.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()

    raise SystemExit("could not determine the Rust host triple; pass --triple")


if __name__ == "__main__":
    raise SystemExit(main())
