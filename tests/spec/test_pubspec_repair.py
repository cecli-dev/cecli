"""Tests for pubspec.yaml dependency repair."""

from __future__ import annotations

from pathlib import Path

from cecli.spec.pubspec_repair import (
    find_missing_pubspec_dependencies,
    parse_pubspec_dependencies,
    repair_pubspec_dependencies,
)


def test_parse_pubspec_dependencies():
    text = """
name: demo
dependencies:
  flutter:
    sdk: flutter
  http: ^1.0.0
dev_dependencies:
  flutter_test:
    sdk: flutter
"""
    deps = parse_pubspec_dependencies(text)
    assert "http" in deps
    assert "flutter" not in deps


def test_find_missing_from_dart_imports(tmp_path: Path):
    (tmp_path / "pubspec.yaml").write_text(
        "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n",
        encoding="utf-8",
    )
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "main.dart").write_text(
        "import 'package:http/http.dart' as http;\nimport 'package:flutter/material.dart';\n",
        encoding="utf-8",
    )
    missing = find_missing_pubspec_dependencies(tmp_path)
    assert missing == ["http"]


def test_repair_dry_run_lists_missing(tmp_path: Path):
    (tmp_path / "pubspec.yaml").write_text(
        "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n",
        encoding="utf-8",
    )
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.dart").write_text(
        "import 'package:provider/provider.dart';\n", encoding="utf-8"
    )
    result = repair_pubspec_dependencies(tmp_path, apply=False)
    assert "provider" in result.missing
    assert result.applied is False


def test_repair_apply_appends_to_pubspec(tmp_path: Path):
    pubspec = tmp_path / "pubspec.yaml"
    pubspec.write_text(
        "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n",
        encoding="utf-8",
    )
    result = repair_pubspec_dependencies(tmp_path, packages=["collection"], apply=True)
    assert result.applied is True
    text = pubspec.read_text(encoding="utf-8")
    assert "collection:" in text
