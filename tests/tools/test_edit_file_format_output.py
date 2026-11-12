"""Regression tests for EditFile.format_output preview parity with execute.

format_output renders a live diff preview of an edit BEFORE execute applies
it. It must resolve the same start_line/end_line inputs that execute accepts;
otherwise a successful edit shows the user
"Preview Unavailable: Content ID Verification Failed" instead of a diff.

Regression cases: @L{num} line references, ``——<content>`` unique-prefix
references, delete operations, and ``@000`` empty-file markers.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.tools import edit_file


class DummyIO:
    def __init__(self):
        self.tool_error = Mock()
        self.tool_warning = Mock()
        self.outputs = []
        self._last_type = False

    def tool_output(self, msg, type=None):
        self.outputs.append(str(msg))
        self._last_type = type

    def read_text(self, path):
        return Path(path).read_text()

    def _detect_newline(self, path):
        data = Path(path).read_bytes()
        if b"\r\n" in data:
            return "\r\n"
        if b"\n" in data:
            return "\n"
        return None

    def write_text(self, path, content):
        # Mirror the real IO: an already-CRLF payload must not be translated
        # again, which would double carriage returns on Windows.
        newline = "" if "\r\n" in content else None
        Path(path).write_text(content, newline=newline)


class DummyChangeTracker:
    def __init__(self):
        self.calls = []

    def track_change(
        self, file_path, change_type, original_content, new_content, metadata, change_id=None
    ):
        self.calls.append(
            {
                "file_path": file_path,
                "change_type": change_type,
                "original_content": original_content,
                "new_content": new_content,
                "metadata": metadata,
                "change_id": change_id,
            }
        )

        return f"change-{len(self.calls)}"


class DummyCoder:
    def __init__(self, root):
        self.root = str(root)
        self.repo = SimpleNamespace(root=str(root))
        self.io = DummyIO()
        self.change_tracker = DummyChangeTracker()
        self.coder_edited_files = set()
        self.files_edited_by_tools = set()
        self.abs_read_only_fnames = set()
        self.abs_fnames = set()
        self.edit_allowed = True
        self.file_read_cache = set()
        self.verbose = False
        self.pretty = False
        self.agent_config = {"diff_colors": False}

    def abs_root_path(self, file_path):
        path = Path(file_path)
        if path.is_absolute():
            return str(path)
        return str((Path(self.root) / path).resolve())

    def get_rel_fname(self, abs_path):
        return str(Path(abs_path).resolve().relative_to(self.root))


@pytest.fixture
def coder_with_file(tmp_path):
    file_path = tmp_path / "example.txt"
    file_path.write_text(
        "def foo():\n"
        "    print('hello')\n"
        "    return 42\n"
        "\n"
        "\n"
        "def bar():\n"
        "    return foo()\n"
    )
    coder = DummyCoder(tmp_path)
    coder.abs_fnames.add(str(file_path.resolve()))
    return coder, file_path


def make_tool_response(edits, wrap_arguments=False):
    arguments = {"edits": edits}
    if wrap_arguments:
        # Some models mirror the OpenAI wire format and double-wrap the real
        # params under a single top-level "arguments" key.
        arguments = {"arguments": json.dumps(arguments)}
    return SimpleNamespace(
        id="test-id",
        type="function",
        function=SimpleNamespace(
            name="EditFile",
            arguments=json.dumps(arguments),
        ),
    )


def preview_output(coder, edits, wrap_arguments=False):
    """Run format_output (as base_coder does before execute) and capture output."""
    edit_file.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="Local"),
        tool_response=make_tool_response(edits, wrap_arguments=wrap_arguments),
    )
    return "\n".join(coder.io.outputs)


def assert_preview_shows_diff(coder, edits):
    output = preview_output(coder, edits)
    assert "Preview Unavailable" not in output
    assert "Cannot verify" not in output
    assert "@@" in output, f"expected a unified diff in preview output:\n{output}"


def test_format_output_resolves_at_l_references(coder_with_file):
    """@L{num} refs: execute succeeds and format_output previews a real diff."""
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@L2",
            "end_line": "@L3",
            "text": '    print("hello")  # edited',
        }
    ]

    assert_preview_shows_diff(coder, edits)

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []
    assert "Applied 1 edits" in result.to_dict()["result"][0]["content"]


def test_format_output_resolves_unique_prefix_references(coder_with_file):
    """``——<content>`` ReadFile-style refs preview correctly."""
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "——    print('hello')",
            "end_line": "——    return 42",
            "text": '    print("hello")  # edited',
        }
    ]

    assert_preview_shows_diff(coder, edits)

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []


def test_format_output_resolves_at_l_delete(coder_with_file):
    """Delete operation with @L{num} refs previews correctly."""
    coder, file_path = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "delete",
            "start_line": "@L2",
            "end_line": "@L2",
            "text": "",
        }
    ]

    assert_preview_shows_diff(coder, edits)

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []
    assert "print('hello')" not in file_path.read_text()


def test_format_output_resolves_at_000_for_empty_file(coder_with_file):
    """@000 markers on an empty file preview and apply cleanly."""
    coder, file_path = coder_with_file
    file_path.write_text("")
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@000",
            "end_line": "@000",
            "text": "hello\nworld",
        }
    ]

    output = preview_output(coder, edits)
    assert "Preview Unavailable" not in output

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []
    assert file_path.read_text() == "hello\nworld"


def test_format_output_mixed_selectors_in_batch(coder_with_file):
    """A batch mixing @L{num} and bare-content selectors previews each edit."""
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@L1",
            "end_line": "@L1",
            "text": "def foo():  # v2",
        },
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "    return 42",
            "end_line": "    return 42",
            "text": "    return 7",
        },
    ]

    output = preview_output(coder, edits)
    assert "Preview Unavailable" not in output
    assert output.count("@@") >= 2

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []


def test_format_output_unwraps_double_wrapped_arguments(coder_with_file):
    """Double-wrapped {"arguments": "{\"edits\": [...]}"} previews a real diff.

    The execution path unwraps this via responses.parse_tool_arguments, so the
    preview (format_output) must resolve the same edits instead of rendering
    nothing.
    """
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@L2",
            "end_line": "@L3",
            "text": '    print("hello")  # edited',
        }
    ]

    output = preview_output(coder, edits, wrap_arguments=True)
    assert "Preview Unavailable" not in output
    assert "@@" in output, f"expected a unified diff in preview output:\n{output}"

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []


def test_description_documents_brace_hint_syntax():
    """The description must document the canonical double-brace hint syntax."""
    description = edit_file.Tool.SCHEMA["function"]["description"]

    assert "@A{{regex}}" in description
    assert "@B{{regex}}" in description
    assert "@A{regex}" not in description
    assert "virtual identifiers" in description
    assert "——" in description
    assert "ReadFile-only" in description
    assert "@C<n>" in description
    assert "@P<n>" in description
    assert "@N<n>" in description
    assert "bare '@A'/'@B' is rejected" in description
    assert "EditFile rejects them" in description
    assert "indentation may be trimmed" not in description


def test_execute_rejects_multiline_anchor(coder_with_file):
    """EditFile must reject multiline start_line/end_line values."""
    coder, file_path = coder_with_file
    original_content = file_path.read_text()

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": "def foo():\n    print('hello')",
                "end_line": "def foo():\n    print('hello')",
                "text": "changed",
            }
        ],
    ).to_dict()

    assert result["errors"]
    assert "single-line anchor" in result["errors"][0]
    assert file_path.read_text() == original_content


def test_execute_appends_with_000_markers(coder_with_file):
    """EditFile supports 000@ for both boundaries as an EOF append."""
    coder, file_path = coder_with_file

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": "000@",
                "end_line": "000@",
                "text": "appended",
            }
        ],
    ).to_dict()

    assert result["errors"] == []
    assert file_path.read_text().endswith("    return foo()\nappended\n")


def test_execute_hint_disambiguates_trimmed_duplicate(coder_with_file):
    """A trimmed anchor plus @L must resolve duplicate lines correctly."""
    coder, file_path = coder_with_file
    file_path.write_text(
        "def alpha():\n" "    return total\n" "\n" "\n" "def beta():\n" "    return total\n"
    )

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": "return total @L6",
                "end_line": "return total @L6",
                "text": "    return 99",
            }
        ],
    ).to_dict()

    assert result["errors"] == []
    lines = file_path.read_text().splitlines()
    assert lines[1] == "    return total"
    assert lines[5] == "    return 99"


@pytest.mark.parametrize(
    "hint",
    ["return total @B{def beta}", "return total @B{{def beta}}"],
)
def test_execute_at_b_disambiguates_trimmed_duplicate(coder_with_file, hint):
    """A trimmed anchor plus @B must pick the occurrence before the regex hit."""
    coder, file_path = coder_with_file
    file_path.write_text(
        "def alpha():\n"
        "    return total\n"
        "\n"
        "\n"
        "def beta():\n"
        "    return total\n"
        "\n"
        "\n"
        "def gamma():\n"
        "    return total\n"
    )

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": hint,
                "end_line": hint,
                "text": "    return 1",
            }
        ],
    ).to_dict()

    assert result["errors"] == []
    lines = file_path.read_text().splitlines()
    assert lines[1] == "    return 1"
    assert lines[5] == "    return total"
    assert lines[9] == "    return total"


@pytest.mark.parametrize(
    "hint",
    ["return total @A{def beta}", "return total @A{{def beta}}"],
)
def test_execute_at_a_accepts_single_or_double_braces(coder_with_file, hint):
    """@A must pick the occurrence after the regex hit with either brace style."""
    coder, file_path = coder_with_file
    file_path.write_text(
        "def alpha():\n" "    return total\n" "\n" "\n" "def beta():\n" "    return total\n"
    )

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": hint,
                "end_line": hint,
                "text": "    return 1",
            }
        ],
    ).to_dict()

    assert result["errors"] == []
    lines = file_path.read_text().splitlines()
    assert lines[1] == "    return total"
    assert lines[5] == "    return 1"


@pytest.mark.parametrize(
    "hint",
    ["@A{{def describe}}", "@B{{def describe}}", "@A", "@B"],
)
def test_execute_rejects_bare_at_hints(coder_with_file, hint):
    """Bare @A/@B hints must be rejected instead of resolving to the hit line."""
    coder, file_path = coder_with_file
    file_path.write_text("def describe(self):\n    return 1\n")

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": hint,
                "end_line": hint,
                "text": "REPLACED",
            }
        ],
    ).to_dict()

    assert result["errors"]
    assert "Bare '@" in result["errors"][0]
    assert file_path.read_text() == "def describe(self):\n    return 1\n"


@pytest.mark.parametrize("hint", ["@C1", "@P1", "@N1", "some text @C1"])
def test_execute_rejects_readfile_only_markers(coder_with_file, hint):
    """@C/@P/@N markers must fail with an EditFile-specific message."""
    coder, file_path = coder_with_file
    original_content = file_path.read_text()

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": hint,
                "end_line": hint,
                "text": "REPLACED",
            }
        ],
    ).to_dict()

    assert result["errors"]
    assert "ReadFile-only" in result["errors"][0]
    assert "not supported by EditFile" in result["errors"][0]
    assert file_path.read_text() == original_content


def test_execute_prepends_with_at_000_markers(coder_with_file):
    """Using @000 for both boundaries inserts at the top of the file."""
    coder, file_path = coder_with_file
    original = file_path.read_text()

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": "@000",
                "end_line": "@000",
                "text": "header",
            }
        ],
    ).to_dict()

    assert result["errors"] == []
    assert file_path.read_text() == "header\n" + original


def test_execute_allows_at_l0_prepend(coder_with_file):
    """@L0 is treated as the top-of-file marker."""
    coder, file_path = coder_with_file
    original = file_path.read_text()

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": "@L0",
                "end_line": "@L0",
                "text": "header",
            }
        ],
    ).to_dict()

    assert result["errors"] == []
    assert file_path.read_text() == "header\n" + original


def test_execute_preserves_crlf_line_endings(coder_with_file):
    """Editing a CRLF file must keep CRLF line endings."""
    coder, file_path = coder_with_file
    file_path.write_bytes(b"first\r\nsecond\r\n")

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "replace",
                "start_line": "second",
                "end_line": "second",
                "text": "SECOND",
            }
        ],
    ).to_dict()

    assert result["errors"] == []
    assert file_path.read_bytes() == b"first\r\nSECOND\r\n"


def test_execute_invalidates_cached_read_ranges(coder_with_file):
    """A successful edit must clear ReadFile's cached ranges for the file."""
    import uuid

    from cecli.helpers.conversation import ConversationService

    coder, file_path = coder_with_file
    coder.uuid = str(uuid.uuid4())
    abs_path = str(file_path.resolve())
    files = ConversationService.get_files(coder)
    files._numbered_contexts[abs_path] = [(1, 1)]
    files._last_merged_ranges[abs_path] = [(1, 1)]
    files._emitted_contexts[abs_path] = [(1, 1)]
    files._file_context_versions[abs_path] = 1

    try:
        result = edit_file.Tool.execute(
            coder,
            edits=[
                {
                    "file_path": "example.txt",
                    "operation": "replace",
                    "start_line": "@L2",
                    "end_line": "@L2",
                    "text": "    print('edited')",
                }
            ],
        ).to_dict()

        assert result["errors"] == []
        assert abs_path not in files._numbered_contexts
        assert abs_path not in files._last_merged_ranges
        assert abs_path not in files._emitted_contexts
        assert abs_path not in files._file_context_versions
    finally:
        ConversationService.destroy_instances(coder.uuid)


def test_format_output_colors_inserted_text_green(coder_with_file):
    """Inserted text is additive, so preview it green like added diff lines."""
    coder, _ = coder_with_file
    coder.agent_config["diff_colors"] = True
    edits = [
        {
            "file_path": "example.txt",
            "operation": "insert",
            "text": "    print('inserted')",
            "start_line": "@L1",
            "position": "after",
        }
    ]

    output = preview_output(coder, edits)

    assert "\033[32m+    print('inserted')\x1b[0m" in output


def test_format_output_leaves_inserted_text_plain_without_diff_colors(coder_with_file):
    """Inserted text stays uncolored when diff colors are disabled."""
    coder, _ = coder_with_file
    coder.agent_config["diff_colors"] = False
    edits = [
        {
            "file_path": "example.txt",
            "operation": "insert",
            "text": "    print('inserted')",
            "start_line": "@L1",
            "position": "after",
        }
    ]

    output = preview_output(coder, edits)

    assert "+    print('inserted')" in output
    assert "\033[32m" not in output


def test_execute_create_writes_new_file(tmp_path):
    """Create writes text to a new path, tracks it, and adds it to context."""
    coder = DummyCoder(tmp_path)
    edits = [
        {
            "file_path": "pkg/new_file.py",
            "operation": "create",
            "text": "print('hi')\n",
        }
    ]

    result = edit_file.Tool.execute(coder, edits=edits).to_dict()

    created = tmp_path / "pkg" / "new_file.py"
    assert result["errors"] == []
    assert "Created pkg/new_file.py" in result["result"][0]["content"]
    assert created.read_text() == "print('hi')\n"
    assert str(created.resolve()) in coder.abs_fnames
    assert coder.change_tracker.calls[0]["original_content"] == ""
    assert coder.change_tracker.calls[0]["new_content"] == "print('hi')\n"


def test_execute_create_fails_when_file_exists(coder_with_file):
    """Create must not overwrite an existing file."""
    coder, file_path = coder_with_file
    original_content = file_path.read_text()

    result = edit_file.Tool.execute(
        coder,
        edits=[{"file_path": "example.txt", "operation": "create", "text": "x"}],
    ).to_dict()

    assert result["errors"]
    assert "already exists" in result["errors"][0]
    assert file_path.read_text() == original_content


def test_execute_create_requires_text(tmp_path):
    """Create without text is rejected."""
    coder = DummyCoder(tmp_path)

    result = edit_file.Tool.execute(
        coder, edits=[{"file_path": "new.txt", "operation": "create"}]
    ).to_dict()

    assert result["errors"]
    assert "'text' parameter is required" in result["errors"][0]
    assert not (tmp_path / "new.txt").exists()


def test_execute_create_rejects_mixed_edits(tmp_path):
    """Create cannot be combined with other edits for the same file."""
    coder = DummyCoder(tmp_path)
    edits = [
        {"file_path": "mix.txt", "operation": "create", "text": "x"},
        {
            "file_path": "mix.txt",
            "operation": "replace",
            "start_line": "@L1",
            "end_line": "@L1",
            "text": "y",
        },
    ]

    result = edit_file.Tool.execute(coder, edits=edits).to_dict()

    assert result["errors"]
    assert "cannot be combined" in result["errors"][0]
    assert not (tmp_path / "mix.txt").exists()


def test_execute_create_dry_run_does_not_write(tmp_path):
    """A dry-run create reports the target without touching the filesystem."""
    coder = DummyCoder(tmp_path)

    result = edit_file.Tool.execute(
        coder,
        edits=[{"file_path": "new.txt", "operation": "create", "text": "x"}],
        dry_run=True,
    ).to_dict()

    assert result["errors"] == []
    assert "Would create new.txt" in result["result"][0]["content"]
    assert not (tmp_path / "new.txt").exists()


def test_execute_create_batches_multiple_files(tmp_path):
    """Several files can be created in a single call."""
    coder = DummyCoder(tmp_path)
    edits = [
        {"file_path": "a.txt", "operation": "create", "text": "aaa\n"},
        {"file_path": "b.txt", "operation": "create", "text": "bbb\n"},
    ]

    result = edit_file.Tool.execute(coder, edits=edits).to_dict()

    assert result["errors"] == []
    assert (tmp_path / "a.txt").read_text() == "aaa\n"
    assert (tmp_path / "b.txt").read_text() == "bbb\n"


def test_format_output_renders_created_text(tmp_path):
    """Created text is additive, so preview it like added diff lines."""
    coder = DummyCoder(tmp_path)
    edits = [{"file_path": "new.txt", "operation": "create", "text": "hello"}]

    output = preview_output(coder, edits)

    assert "+hello" in output
