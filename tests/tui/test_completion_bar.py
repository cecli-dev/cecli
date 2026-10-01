import os
import sys
from unittest import mock

import pytest

from cecli.tui.widgets.completion_bar import CompletionBar

IS_WINDOWS = sys.platform == "win32"

# Capture the real relpath before any test patches os.path.relpath, so fake
# implementations can delegate to it without recursing into the mock.
original_relpath = os.path.relpath


@pytest.mark.skipif(IS_WINDOWS, reason="POSIX-only path separators")
def test_absolute_path_suggestions_stay_absolute():
    """Absolute suggestions are not converted to relative (../) paths."""
    bar = CompletionBar(
        suggestions=["/mnt/", "/srv/", "/etc/", "/dev/", "/opt/"],
        prefix="/workspace test /",
    )
    bar._compute_display_names()

    # The stored suggestions must remain absolute so selection inserts the correct path.
    assert bar.suggestions == ["/mnt/", "/srv/", "/etc/", "/dev/", "/opt/"]
    # The shared filesystem root is shown once as a prefix.
    assert bar._common_prefix == "/"
    assert bar._display_names == ["mnt/", "srv/", "etc/", "dev/", "opt/"]
    assert bar.current_selection == "/mnt/"


@pytest.mark.skipif(IS_WINDOWS, reason="POSIX-only path separators")
def test_relative_path_suggestions_kept():
    """Project-relative suggestions keep their existing display behavior."""
    bar = CompletionBar(
        suggestions=["src/main.py", "src/util.py", "tests/test.py"],
        prefix="/add ",
    )
    bar._compute_display_names()

    assert bar.suggestions == ["src/main.py", "src/util.py", "tests/test.py"]
    assert bar._display_names == ["src/main.py", "src/util.py", "tests/test.py"]


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows-only path separators")
def test_windows_absolute_path_suggestions_stay_absolute():
    """Absolute suggestions are not converted to relative paths (Windows)."""
    suggestions = ["C:\\mnt\\", "C:\\srv\\", "C:\\etc\\", "C:\\dev\\", "C:\\opt\\"]
    bar = CompletionBar(suggestions=suggestions, prefix="C:\\workspace test ")

    bar._compute_display_names()

    # The stored suggestions must remain absolute so selection inserts the correct path.
    assert bar.suggestions == suggestions
    # The shared drive root is shown once as a prefix.
    assert bar._common_prefix == "C:\\"
    assert bar._display_names == ["mnt\\", "srv\\", "etc\\", "dev\\", "opt\\"]
    assert bar.current_selection == "C:\\mnt\\"


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows-only path separators")
def test_windows_relative_path_suggestions_kept():
    """Project-relative suggestions keep their display behavior (Windows)."""
    suggestions = ["src\\main.py", "src\\util.py", "tests\\test.py"]
    bar = CompletionBar(suggestions=suggestions, prefix="/add ")

    bar._compute_display_names()

    assert bar.suggestions == suggestions
    assert bar._display_names == suggestions


def test_relpath_cross_drive_falls_back():
    """os.path.relpath() raising ValueError (Windows cross-drive) must not crash.

    Simulates the reported crash: C:-relative suggestions mixed with an
    absolute path on another drive (E:), i.e.
    "ValueError: path is on mount 'E:', start on mount 'C:'".
    """

    def fake_relpath(path, start=None):
        if "E:\\" in path:
            raise ValueError("path is on mount 'E:', start on mount 'C:'")
        return original_relpath(path)

    with mock.patch("os.path.relpath", side_effect=fake_relpath):
        # Must not raise; the cross-drive suggestion is displayed as-is.
        bar = CompletionBar(
            suggestions=[
                "../.cecli/rules.md",
                "E:\\My_Mods\\data\\file1.txt",
            ],
            prefix="/drop ",
        )
        bar._compute_display_names()

    assert "E:\\My_Mods\\data\\file1.txt" in bar._display_names


def test_commonpath_mixed_drives_falls_back():
    """os.path.commonpath() raising ValueError (mixed drives) must not crash.

    The same Windows limitation hits the common prefix step one line after
    relpath; the bar must fall back to showing candidates as-is.
    """
    with (
        mock.patch("os.path.commonpath", side_effect=ValueError("Can't mix paths")),
        mock.patch("os.path.relpath", side_effect=lambda path, start=None: path),
    ):
        # Must not raise at the commonpath step either.
        bar = CompletionBar(
            suggestions=[
                "E:\\My_Mods\\data\\file1.txt",
                "../other/file2.txt",
            ],
            prefix="/drop ",
        )
        bar._compute_display_names()

    assert "E:\\My_Mods\\data\\file1.txt" in bar._display_names


def test_same_directory_suggestions_compress():
    """Suggestions in one directory still collapse to a shared prefix + basenames."""
    sep = os.sep
    bar = CompletionBar(
        suggestions=[
            "src" + sep + "one.py",
            "src" + sep + "two.py",
        ],
        prefix="/add ",
    )
    bar._compute_display_names()

    assert bar._common_prefix == "src" + sep
    assert bar._display_names == ["one.py", "two.py"]
