"""Detect and repair missing Dart package dependencies in pubspec.yaml."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DART_PKG_IMPORT = re.compile(
    r"""^\s*import\s+['"]package:([a-zA-Z_][\w]*)/""",
    re.MULTILINE,
)

_BUILTIN_PACKAGES = frozenset(
    {
        "flutter",
        "flutter_test",
        "integration_test",
        "flutter_localizations",
        "flutter_web_plugins",
    }
)

_DEP_SECTION = re.compile(r"^(\s*)(dependencies|dev_dependencies):\s*$", re.MULTILINE)


@dataclass(frozen=True)
class PubspecRepairResult:
    missing: tuple[str, ...]
    added: tuple[str, ...]
    applied: bool
    message: str


def collect_dart_package_imports(workspace: str | Path) -> set[str]:
    """Package names imported from ``lib/`` and ``test/`` Dart sources."""
    root = Path(workspace).resolve()
    packages: set[str] = set()
    for sub in ("lib", "test"):
        base = root / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*.dart"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in _DART_PKG_IMPORT.finditer(text):
                name = match.group(1)
                if name not in _BUILTIN_PACKAGES:
                    packages.add(name)
    return packages


def parse_pubspec_dependencies(pubspec_text: str) -> set[str]:
    """Declared package names under dependencies / dev_dependencies."""
    declared: set[str] = set()
    section: str | None = None
    for line in pubspec_text.splitlines():
        stripped = line.strip()
        if stripped in ("dependencies:", "dev_dependencies:"):
            section = stripped[:-1]
            continue
        if section and stripped and not stripped.startswith("#"):
            if re.match(r"^[a-zA-Z_][\w]*:", stripped) and not stripped.startswith("sdk:"):
                key = stripped.split(":", 1)[0].strip()
                if key not in ("flutter", "sdk"):
                    declared.add(key)
            elif line and not line[0].isspace():
                section = None
    return declared


def find_missing_pubspec_dependencies(workspace: str | Path) -> list[str]:
    root = Path(workspace).resolve()
    pubspec = root / "pubspec.yaml"
    if not pubspec.is_file():
        return []
    try:
        text = pubspec.read_text(encoding="utf-8")
    except OSError:
        return []
    used = collect_dart_package_imports(root)
    declared = parse_pubspec_dependencies(text)
    return sorted(used - declared)


def _append_dependencies(pubspec_text: str, packages: list[str]) -> str:
    if not packages:
        return pubspec_text
    lines = pubspec_text.splitlines()
    insert_at: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == "dependencies:":
            insert_at = idx + 1
            break
    if insert_at is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("dependencies:")
        insert_at = len(lines)
    indent = "  "
    for pkg in packages:
        lines.insert(insert_at, f"{indent}{pkg}: any")
        insert_at += 1
    return "\n".join(lines) + ("\n" if pubspec_text.endswith("\n") else "")


def _run_flutter_pub_add(workspace: Path, packages: list[str]) -> tuple[bool, str]:
    from cecli.spec.implement import resolve_flutter_executable

    flutter = resolve_flutter_executable()
    if not flutter:
        return False, "flutter not found on PATH"
    cmd = [flutter, "pub", "add", *packages]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out[-2000:] if out else f"exit {proc.returncode}"


def repair_pubspec_dependencies(
    workspace: str | Path,
    packages: list[str] | None = None,
    *,
    apply: bool = False,
) -> PubspecRepairResult:
    """Detect or add missing pub dependencies (flutter pub add when possible)."""
    root = Path(workspace).resolve()
    pubspec = root / "pubspec.yaml"
    if not pubspec.is_file():
        return PubspecRepairResult((), (), False, "pubspec.yaml missing")

    missing = list(packages or find_missing_pubspec_dependencies(root))
    if not missing:
        return PubspecRepairResult((), (), False, "No missing package dependencies detected.")

    if not apply:
        return PubspecRepairResult(
            tuple(missing),
            (),
            False,
            f"Missing dependencies: {', '.join(missing)}. Re-run with --apply.",
        )

    ok, output = _run_flutter_pub_add(root, missing)
    if ok:
        return PubspecRepairResult(
            tuple(missing),
            tuple(missing),
            True,
            output or f"Added: {', '.join(missing)}",
        )

    try:
        original = pubspec.read_text(encoding="utf-8")
        updated = _append_dependencies(original, missing)
        pubspec.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return PubspecRepairResult(tuple(missing), (), False, f"Failed to edit pubspec.yaml: {exc}")

    return PubspecRepairResult(
        tuple(missing),
        tuple(missing),
        True,
        f"flutter pub add failed ({output}); appended {', '.join(missing)} under dependencies:",
    )


def pubspec_repair_snapshot_lines(workspace: str | Path) -> list[str]:
    """Optional implement-snapshot lines when imports lack pubspec entries."""
    missing = find_missing_pubspec_dependencies(workspace)
    if not missing:
        return []
    preview = ", ".join(f"`{p}`" for p in missing[:6])
    extra = f" (+{len(missing) - 6} more)" if len(missing) > 6 else ""
    return [
        f"- **pubspec.yaml** — missing dependencies: {preview}{extra}. "
        "Add with **EditText** on `pubspec.yaml` or run "
        "`bright-vision-tasks repair-pubspec --apply`."
    ]
