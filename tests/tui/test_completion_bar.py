import sys

import pytest

from cecli.tui.widgets.completion_bar import CompletionBar

IS_WINDOWS = sys.platform == "win32"


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
