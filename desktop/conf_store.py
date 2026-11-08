"""Persistent desktop workspace configuration backed by cecli YAML files.

Resolution mirrors cecli's config loader: `~/.cecli/conf.yml` is read first,
then the project-local `<workspace>/.cecli/conf.yml`, with the project file
winning on top-level keys. The `desktop.folders` key holds entries shaped like
`{"path": "/abs/path", "name": "Display Name"}`. Writes go to the project
file and preserve every unrelated key.

`CECLI_DESKTOP_CONF_FILE` overrides the project file path and
`CECLI_DESKTOP_GLOBAL_CONF` overrides the global file path (used by tests).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def _default_global_path() -> Path:
    override = os.environ.get("CECLI_DESKTOP_GLOBAL_CONF")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cecli" / "conf.yml"


def _default_project_path(workspace: Path) -> Path:
    override = os.environ.get("CECLI_DESKTOP_CONF_FILE")
    if override:
        return Path(override).expanduser()
    return workspace / ".cecli" / "conf.yml"


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read one YAML mapping, treating a missing or broken file as empty."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_dump(path: Path, data: dict[str, Any]) -> None:
    """Write YAML via a sibling temp file so a crash never truncates conf.yml."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
    )
    try:
        with handle:
            yaml.safe_dump(data, handle, sort_keys=False, default_flow_style=False)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    """Return a `{path, name}` entry, or None when the shape is unusable."""
    if isinstance(entry, str):
        raw_path, name = entry, None
    elif isinstance(entry, dict):
        raw_path, name = entry.get("path"), entry.get("name")
    else:
        return None

    if not isinstance(raw_path, str) or not raw_path.strip():
        return None

    path = os.path.abspath(os.path.expanduser(raw_path.strip()))
    display = name.strip() if isinstance(name, str) and name.strip() else Path(path).name or path
    return {"path": path, "name": display}


def workspace_state(entry: dict[str, Any]) -> dict[str, Any]:
    """Annotate one entry with whether its directory currently exists."""
    path = entry.get("path") or ""
    valid = bool(path) and os.path.isdir(path)
    state = dict(entry)
    state["valid"] = valid
    if not valid:
        state["error"] = f"Workspace does not exist: {path}"
    return state


class ConfStore:
    """Read and mutate the `desktop.folders` list in cecli's YAML config."""

    def __init__(
        self,
        workspace: str | Path,
        global_path: str | Path | None = None,
        project_path: str | Path | None = None,
    ) -> None:
        resolved = Path(os.path.abspath(os.path.expanduser(str(workspace))))
        self.workspace = resolved
        self.global_path = Path(global_path).expanduser() if global_path else _default_global_path()
        self.project_path = (
            Path(project_path).expanduser() if project_path else _default_project_path(resolved)
        )

    def config(self) -> dict[str, Any]:
        """The shallow-merged config, project values replacing global ones."""
        merged = _read_yaml(self.global_path)
        merged.update(_read_yaml(self.project_path))
        return merged

    def model(self) -> str | None:
        """The configured default model, if any."""
        config = self.config()
        model = config.get("model") or config.get("agent-model")
        return model if isinstance(model, str) and model.strip() else None

    def workspaces(self) -> list[dict[str, Any]]:
        """Configured folders in file order, with invalid entries still present."""
        desktop = self.config().get("desktop")
        folders = desktop.get("folders") if isinstance(desktop, dict) else None
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in folders if isinstance(folders, list) else []:
            entry = _normalize_entry(raw)
            if entry is None:
                continue
            key = os.path.realpath(entry["path"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
        return entries

    def workspace_states(self) -> list[dict[str, Any]]:
        """Configured folders annotated with `valid`/`error`."""
        return [workspace_state(entry) for entry in self.workspaces()]

    def add_workspace(self, path: str, name: str | None = None) -> dict[str, Any]:
        """Validate, persist and return one new folder entry."""
        entry = _normalize_entry({"path": path, "name": name})
        if entry is None:
            raise ValueError("A workspace path is required")
        if not os.path.isdir(entry["path"]):
            raise ValueError(f"Workspace does not exist: {entry['path']}")

        entries = self.workspaces()
        real = os.path.realpath(entry["path"])
        existing = next((item for item in entries if os.path.realpath(item["path"]) == real), None)
        if existing is not None:
            existing["name"] = entry["name"]
            self._write_workspaces(entries)
            return existing

        entries.append(entry)
        self._write_workspaces(entries)
        return entry

    def remove_workspace(self, path: str) -> bool:
        """Drop the folder whose real path matches ``path``; returns whether it existed."""
        real = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
        entries = self.workspaces()
        kept = [item for item in entries if os.path.realpath(item["path"]) != real]
        if len(kept) == len(entries):
            return False
        self._write_workspaces(kept)
        return True

    def set_workspaces(self, entries: list[dict[str, Any]]) -> None:
        """Replace the folder list, preserving unrelated config keys."""
        self._write_workspaces(entries)

    def _write_workspaces(self, entries: list[dict[str, Any]]) -> None:
        """Persist exactly the given entries to the project config file."""
        data = _read_yaml(self.project_path)
        if not isinstance(data.get("desktop"), dict):
            data["desktop"] = {}
        data["desktop"]["folders"] = [
            {"path": item["path"], "name": item.get("name") or Path(item["path"]).name}
            for item in entries
        ]
        _atomic_dump(self.project_path, data)
