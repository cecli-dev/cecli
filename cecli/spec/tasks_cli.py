"""Workspace task / spec progress CLI (headless, no interactive cecli shell)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from cecli.spec.agent_todos import import_agent_plan_for_workspace
from cecli.spec.progress import (
    implementation_steps,
    materialize_checklist_from_tasks_md,
    next_open_implementation_step,
)
from cecli.spec.pubspec_repair import repair_pubspec_dependencies
from cecli.spec.steering import scaffold_steering_files, scan_steering_files
from cecli.spec.todos import WorkspaceTodos


def _resolve_item(api: WorkspaceTodos, todo_id: str | None):
    store = api.load()
    if todo_id:
        return api.find(store, todo_id)
    if store.active_id:
        return api.find(store, store.active_id)
    return store.todos[0] if store.todos else None


def cmd_materialize(workspace: Path, todo_id: str | None) -> int:
    api = WorkspaceTodos(workspace)
    item = _resolve_item(api, todo_id)
    if item is None:
        print("No task found.", file=sys.stderr)
        return 1
    checklist = materialize_checklist_from_tasks_md(item)
    if not checklist:
        print("Nothing to materialize (no numbered steps in tasks_md).", file=sys.stderr)
        return 1
    updated, _ = api.update(item.id, checklist=checklist)
    print(
        json.dumps(
            {"todo_id": updated.id, "checklist": [asdict(c) for c in updated.checklist]}, indent=2
        )
    )
    return 0


def cmd_progress(workspace: Path, todo_id: str | None) -> int:
    api = WorkspaceTodos(workspace)
    item = _resolve_item(api, todo_id)
    if item is None:
        print("No task found.", file=sys.stderr)
        return 1
    steps = implementation_steps(item)
    nxt = next_open_implementation_step(item, None)
    payload = {
        "todo_id": item.id,
        "title": item.title,
        "steps": [
            {
                "step_id": s.step_id,
                "text": s.text,
                "done": s.done,
                "current": s.current,
                "verify_cmd": s.verify_cmd,
            }
            for s in steps
        ],
        "next_open": (
            {
                "step_id": nxt.step_id,
                "text": nxt.text,
                "verify_cmd": nxt.verify_cmd,
            }
            if nxt
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_sync_agent(workspace: Path) -> int:
    store = import_agent_plan_for_workspace(workspace)
    print(json.dumps({"active_id": store.active_id, "todos": len(store.todos)}, indent=2))
    return 0


def _steering_payload(snapshot) -> dict:
    return {
        "has_content": snapshot.has_content,
        "file_count": snapshot.file_count,
        "main": asdict(snapshot.main) if snapshot.main else None,
        "fragments": [asdict(fragment) for fragment in snapshot.fragments],
    }


def cmd_steering_scan(workspace: Path) -> int:
    snapshot = scan_steering_files(workspace)
    print(json.dumps(_steering_payload(snapshot), indent=2))
    return 0


def cmd_steering_scaffold(workspace: Path) -> int:
    created = scaffold_steering_files(workspace)
    snapshot = scan_steering_files(workspace)
    print(
        json.dumps(
            {"created": created, **_steering_payload(snapshot)},
            indent=2,
        )
    )
    return 0


def cmd_repair_pubspec(workspace: Path, *, apply: bool) -> int:
    result = repair_pubspec_dependencies(workspace, apply=apply)
    print(
        json.dumps(
            {
                "missing": list(result.missing),
                "added": list(result.added),
                "applied": result.applied,
                "message": result.message,
            },
            indent=2,
        )
    )
    return 0 if result.applied or not result.missing else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bright-vision-tasks",
        description="Spec task progress utilities (materialize, sync, pubspec repair).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Git workspace root (default: cwd)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_mat = sub.add_parser("materialize", help="Build checklist rows from tasks_md")
    p_mat.add_argument("--todo-id", default=None, help="Task id (default: active)")

    p_prog = sub.add_parser("progress", help="Print unified implementation progress JSON")
    p_prog.add_argument("--todo-id", default=None)

    sub.add_parser("sync-agent", help="Import agent todo.txt into workspace Tasks")

    p_pub = sub.add_parser("repair-pubspec", help="Detect or add missing Dart pub dependencies")
    p_pub.add_argument(
        "--apply", action="store_true", help="Run flutter pub add or edit pubspec.yaml"
    )

    p_steer = sub.add_parser("steering", help="Project steering files (.cecli/STEERING.md)")
    steer_sub = p_steer.add_subparsers(dest="steering_cmd", required=True)
    steer_sub.add_parser("scan", help="List steering markdown files as JSON")
    steer_sub.add_parser("scaffold", help="Create STEERING.md template when missing")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"Not a directory: {workspace}", file=sys.stderr)
        return 1

    if args.command == "materialize":
        return cmd_materialize(workspace, args.todo_id)
    if args.command == "progress":
        return cmd_progress(workspace, args.todo_id)
    if args.command == "sync-agent":
        return cmd_sync_agent(workspace)
    if args.command == "repair-pubspec":
        return cmd_repair_pubspec(workspace, apply=args.apply)
    if args.command == "steering":
        if args.steering_cmd == "scan":
            return cmd_steering_scan(workspace)
        if args.steering_cmd == "scaffold":
            return cmd_steering_scaffold(workspace)
        parser.error(f"unknown steering command: {args.steering_cmd}")
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
