import base64
import os
import re
import shutil
from pathlib import Path

import oslex

from cecli.helpers.file_exclusions import DEFAULT_EXCLUDE_DIRS as SHARED_EXCLUDE_DIRS
from cecli.helpers.file_exclusions import GREP_EXTRA_EXCLUDE_DIRS
from cecli.helpers.hashline import strip_hashline
from cecli.run_cmd import run_cmd_subprocess
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError, is_creator_coder
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations
from cecli.utils import safe_relpath

# Default directories to exclude from search results across various languages.
# The canonical noise list is shared; grep additionally hides source-like dirs.
DEFAULT_EXCLUDE_DIRS = [*sorted(SHARED_EXCLUDE_DIRS), *GREP_EXTRA_EXCLUDE_DIRS]


# Default files to exclude from search results (e.g. past agent conversations).
DEFAULT_EXCLUDE_FILES = [
    "chat-history.md",
    "chat-history-search-replace-gold.txt",
    "*.history.md",
    "*.llm.history",
    "*.input.history",
]


# Output-shaping limits. These bound what is sent to the model while keeping
# match locations intact (counts and line numbers survive truncation).
MAX_MATCHES_PER_FILE = 10
MAX_ADDITIONAL_LINE_NUMBERS = 10
MAX_FILES = 20
MAX_TOTAL_SIZE = 50000
MAX_LINE_LENGTH = 256
MAX_LINE_NUMBERS = 50
MAX_CONTEXT_LINES = 5


def _should_use_regex(pattern, requested):
    """Choose regex mode, auto-detecting common regex syntax only for auto mode."""
    if requested is False:
        return False

    if requested is True:
        return True

    return _looks_like_regex(pattern)


def _has_nonempty_alternation(pattern):
    """Return True when every alternation branch in *pattern* is non-empty."""
    parts = re.split(r"(?<!\\)\|", pattern)

    return len(parts) > 1 and all(parts)


def _has_regex_meta(pattern):
    """Return True when a literal search might have been intended as regex."""
    if re.search(r"\\|[.^$\[\](){}*+?]", pattern):
        return True

    return _has_nonempty_alternation(pattern)


def _looks_like_regex(pattern):
    """Detect strong regex signals without treating ordinary code punctuation as regex."""
    if _has_nonempty_alternation(pattern):
        return True

    if pattern.startswith("^") or pattern.endswith("$"):
        return True

    if re.search(r"\(\?|\.\*|\.\+|\.\?|\{\d+(?:,\d*)?\}", pattern):
        return True

    return bool(re.search(r"\\(?:[AbBdDsSwWZz]|p\{|P\{|[.^$*+?()\[\]{}|\\/-])", pattern))


def _needs_pcre2(pattern):
    """Return True for regex constructs unsupported by ripgrep's default engine."""
    return bool(re.search(r"\(\?(?:=|!|<=|<!)|\\(?:[1-9]|k<|K)", pattern))


_GREP_PCRE_CACHE = {}


def _grep_supports_pcre(tool_path):
    """Probe whether GNU grep supports PCRE via -P."""
    import subprocess

    if tool_path in _GREP_PCRE_CACHE:
        return _GREP_PCRE_CACHE[tool_path]

    try:
        result = subprocess.run(
            [tool_path, "-P", "-e", ""],
            input="",
            capture_output=True,
            timeout=5,
            text=True,
        )
        supported = result.returncode in (0, 1)
    except (subprocess.TimeoutExpired, OSError):
        supported = False

    _GREP_PCRE_CACHE[tool_path] = supported
    return supported


def _build_exclude_args(tool_name, cmd_args, exclude_cecli=True):
    """Add exclusion arguments for common build/artifact dirs and history files."""
    for exclude_dir in DEFAULT_EXCLUDE_DIRS:
        if exclude_dir == ".cecli" and not exclude_cecli:
            continue
        if tool_name == "rg":
            cmd_args.extend(["-g", f"!{exclude_dir}"])
        elif tool_name == "ag":
            cmd_args.extend(["--ignore-dir", exclude_dir])
        elif tool_name == "grep":
            cmd_args.extend(["--exclude-dir", exclude_dir])
    for exclude_file in DEFAULT_EXCLUDE_FILES:
        if tool_name == "rg":
            cmd_args.extend(["-g", f"!{exclude_file}"])
        elif tool_name == "ag":
            cmd_args.extend(["--ignore", exclude_file])
        elif tool_name == "grep":
            cmd_args.extend(["--exclude", exclude_file])
    return cmd_args


def _split_glob_patterns(file_pattern):
    """Split a comma-separated glob list without breaking brace expansions."""
    patterns = []
    current = []
    depth = 0

    for char in file_pattern or "*":
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth = max(depth - 1, 0)

        if char == "," and depth == 0:
            pattern = "".join(current).strip()
            if pattern:
                patterns.append(pattern)
            current = []
        else:
            current.append(char)

    pattern = "".join(current).strip()
    if pattern:
        patterns.append(pattern)

    return patterns or ["*"]


def _parse_context_line_count(value, name):
    """Clamp a context line count and return the value plus any warning."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0, f"{name} must be an integer; using 0."

    clamped = max(min(count, MAX_CONTEXT_LINES), 0)
    if clamped != count:
        return clamped, f"{name} clamped from {count} to {clamped}."

    return clamped, None


def _parse_count_output(output, null_separated=False):
    """Parse grep -c output (file:count per line) into a dict."""
    counts = {}
    if not output:
        return counts

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        if null_separated:
            if "\0" not in line:
                continue
            filepath, count_text = line.split("\0", 1)
            count_text = count_text.strip()
            try:
                count_val = int(count_text)
                if count_val > 0:
                    counts[filepath] = count_val
            except ValueError:
                pass
            continue

        # Format: filepath:count
        # Use rsplit to handle paths that may contain colons
        idx = line.rfind(":")
        if idx > 0:
            filepath = line[:idx]
            try:
                count_val = int(line[idx + 1 :])
                if count_val > 0:
                    counts[filepath] = count_val
            except (ValueError, IndexError):
                pass
    return counts


def _parse_content_into_files(output, null_separated=False):
    """Parse grep -rn output into per-file groups.

    Returns list of dicts with keys: path, match_count, content_lines
    Content lines preserve the original grep format (with : for matches, - for context).
    Merges entries for the same file that appear in non-contiguous match groups.
    When *null_separated* is set, each line is ``path\\0line:content``.
    """
    if not output:
        return []

    lines = output.splitlines()
    if not lines:
        return []

    # Use a dict to accumulate file groups, keyed by filepath
    # This handles interleaved results (file1 -> file2 -> file1) by merging
    file_groups = {}  # filepath -> {path, match_count, content_parts}
    file_order = []  # ordered list of filepaths as they first appear

    current_file = None
    current_lines = []
    match_count = 0

    def _flush_current():
        nonlocal current_file, current_lines, match_count
        if current_file is None or not current_lines:
            return

        if current_file in file_groups:
            # Merge into existing entry
            existing = file_groups[current_file]
            existing["match_count"] += match_count
            existing["content_parts"].append("\n".join(current_lines))
        else:
            # New file entry
            file_groups[current_file] = {
                "path": current_file,
                "match_count": match_count,
                "content_parts": ["\n".join(current_lines)],
            }
            file_order.append(current_file)

        current_file = None
        current_lines = []
        match_count = 0

    for line in lines:
        # Skip separator lines ("--" between non-contiguous match groups)
        if line == "--":
            continue

        if null_separated:
            if "\0" not in line:
                continue

            filepath, rest = line.split("\0", 1)
            entry = re.match(r"^(\d+)([:-])(.*)$", rest)
            if not entry:
                continue

            line_text = (
                f"{filepath}{entry.group(2)}{entry.group(1)}{entry.group(2)}{entry.group(3)}"
            )
            is_match_line = entry.group(2) == ":"
        else:
            # Try to extract filename from the line prefix
            # Match lines:   path:line:content
            # Context lines: path-line-content  (with - hyphen after line number)
            m = re.match(r"^(.+?)[:-](\d+)[:-]", line)
            if not m:
                # Line that doesn't match the pattern (e.g. rg --heading output)
                if current_file is not None:
                    current_lines.append(line)
                continue

            filepath = m.group(1)
            # Actually check: match lines have :LINE:, context lines have -LINE-
            # The format is: path:line:content or path-line-content
            # Check whether the char after line num is : or -
            line_num_end = len(filepath) + 1 + len(m.group(2))
            is_match_line = line_num_end < len(line) and line[line_num_end] == ":"
            line_text = line

        if current_file is None:
            current_file = filepath
            match_count = 1 if is_match_line else 0
            current_lines = [line_text]
        elif filepath == current_file:
            current_lines.append(line_text)
            if is_match_line:
                match_count += 1
        else:
            # Different file - flush current block before switching
            _flush_current()
            current_file = filepath
            match_count = 1 if is_match_line else 0
            current_lines = [line_text]

    # Flush the last file's accumulated block
    _flush_current()

    # Build final list preserving first-seen order
    files = []
    for fpath in file_order:
        group = file_groups[fpath]
        files.append(
            {
                "path": group["path"],
                "match_count": group["match_count"],
                "content": "\n".join(group["content_parts"]),
            }
        )

    return files


def _extract_warnings(output, null_separated=False):
    """Return diagnostic lines that are not match or context records."""
    warnings = []
    if not output:
        return warnings

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line == "--":
            continue

        if null_separated:
            if "\0" not in line:
                warnings.append(line)
        elif re.match(r"^(?:rg|ag|grep)(?:\.exe)?:\s", line, re.IGNORECASE):
            warnings.append(line)

    return warnings


def _append_warnings(op_result, warnings):
    """Add warnings to an operation result without duplicating messages."""
    bucket = op_result.setdefault("warnings", [])
    for warning in warnings:
        if warning not in bucket:
            bucket.append(warning)


def _cap_line(text, max_length=MAX_LINE_LENGTH):
    """Truncate a single line, marking how many characters were omitted."""
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}…(+{len(text) - max_length} chars)"


def _extract_file_entries(abs_path, content):
    """Split raw grep content into ``{line, text, is_match}`` entries.

    Match lines use ``path:line:text`` and context lines ``path-line-text``, the
    convention emitted by ``_parse_content_into_files`` and
    ``_parse_select_string_output``.
    """
    match_re = re.compile(r"^" + re.escape(abs_path) + r":(\d+):(.*)$")
    context_re = re.compile(r"^" + re.escape(abs_path) + r"-(\d+)-(.*)$")
    entries = []
    for raw_line in content.splitlines():
        # Select-String marks matches with "> " and indents context lines.
        line = raw_line[2:] if raw_line.startswith("> ") else raw_line.lstrip(" ")
        match = match_re.match(line)
        if match:
            entries.append({"line": int(match.group(1)), "text": match.group(2), "is_match": True})
            continue
        context = context_re.match(line)
        if context:
            entries.append(
                {"line": int(context.group(1)), "text": context.group(2), "is_match": False}
            )
    return entries


def _build_powershell_exclude_regex(exclude_dirs=None, exclude_files=None, exclude_cecli=True):
    """Build a PowerShell -notmatch regex that skips default build/artifact dirs.

    Also skips default history files (matched by basename suffix).
    """
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDE_DIRS
    if exclude_files is None:
        exclude_files = DEFAULT_EXCLUDE_FILES
    fragments = []
    for entry in exclude_dirs:
        if entry == ".cecli" and not exclude_cecli:
            continue
        # Escape the literal text, then turn * globs into path-segment wildcards.
        frag = re.escape(entry).replace(r"\*", r"[^\\/]*")
        fragments.append(r"(?:\\|/)(?:" + frag + r")(?:\\|/|$)")
    for entry in exclude_files:
        frag = re.escape(entry).replace(r"\*", r"[^\\/]*")
        fragments.append(r"(?:\\|/)" + frag + r"$")
    if not fragments:
        return None
    return r"(?:" + "|".join(fragments) + r")"


def _build_powershell_search_script(
    search_dir_path,
    pattern,
    file_pattern,
    use_regex,
    case_insensitive,
    context_before,
    context_after,
    count_only,
    exclude_cecli=True,
):
    """Build a PowerShell pipeline that mimics rg/ag/grep via Select-String."""

    def _ps_quote(value):
        # Embed a value in a PowerShell single-quoted string ('' escapes a quote).
        return "'" + str(value).replace("'", "''") + "'"

    parts = ["Get-ChildItem", "-LiteralPath", _ps_quote(search_dir_path), "-Recurse", "-File"]

    if file_pattern != "*":
        parts.extend(["-Filter", _ps_quote(file_pattern)])

    exclude_regex = _build_powershell_exclude_regex(exclude_cecli=exclude_cecli)
    if exclude_regex:
        parts.extend(
            [
                "|",
                "Where-Object",
                "{",
                "$_.FullName",
                "-notmatch",
                _ps_quote(exclude_regex),
                "}",
            ]
        )

    parts.extend(["|", "Select-String", "-Pattern", _ps_quote(pattern)])

    if not use_regex:
        parts.append("-SimpleMatch")
    if not case_insensitive:
        parts.append("-CaseSensitive")

    if count_only:
        parts.extend(
            [
                "|",
                "Group-Object",
                "Path",
                "|",
                "ForEach-Object",
                "{",
                '"$($_.Name):$($_.Count)"',
                "}",
            ]
        )
    else:
        parts.extend(["-Context", f"{context_before},{context_after}"])

    return " ".join(parts)


def _encode_powershell_command(script, powershell_path):
    """Encode a PowerShell script for -EncodedCommand and return the full command."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return (
        f"{powershell_path} -NoProfile -NonInteractive -OutputFormat Text "
        f"-EncodedCommand {encoded}"
    )


def _parse_select_string_output(output, repo_root):
    """Parse Select-String (PowerShell) output into per-file groups.

    With -OutputFormat Text, each match is rendered as:
      <path>:<line>:<content>             (no context)
    and with context as:
      > <path>:<line>:<content>           (match line)
      <path>:<line>:<content>             (context line, leading spaces)

    PowerShell renders paths relative to the current directory, so each path is
    re-resolved against *repo_root* to an absolute path. This keeps the parsed
    groups consistent with the count pass (Group-Object Path -> absolute paths)
    and with the downstream truncation/relpath logic.
    """
    if not output:
        return []

    file_groups = {}
    file_order = []

    def _flush(current_file, current_lines, match_count):
        if current_file is None or not current_lines:
            return
        if current_file in file_groups:
            existing = file_groups[current_file]
            existing["match_count"] += match_count
            existing["content_parts"].append("\n".join(current_lines))
        else:
            file_groups[current_file] = {
                "path": current_file,
                "match_count": match_count,
                "content_parts": ["\n".join(current_lines)],
            }
            file_order.append(current_file)

    entry_re = re.compile(r"^(.+?)[:-](\d+)[:-](.*)$")

    current_file = None
    current_lines = []
    match_count = 0

    for raw_line in output.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue

        # Detect Select-String prefix markers: '> ' for matches, spaces for context.
        prefix = ""
        is_match = True
        rest = line
        if line.startswith("> "):
            prefix = "> "
            rest = line[2:]
        elif line.startswith("  "):
            prefix = "  "
            rest = line[2:]
            is_match = False
        elif line.startswith(" "):
            prefix = " "
            rest = line.lstrip(" ")
            is_match = False

        m = entry_re.match(rest)
        if not m:
            if current_file is not None:
                current_lines.append(line)
            continue

        filepath = m.group(1)
        abs_path = (
            filepath
            if os.path.isabs(filepath)
            else os.path.normpath(os.path.join(repo_root, filepath))
        )
        rebuilt = prefix + abs_path + rest[len(filepath) :]

        if current_file is None:
            current_file = abs_path
            match_count = 1 if is_match else 0
            current_lines = [rebuilt]
        elif abs_path == current_file:
            current_lines.append(rebuilt)
            if is_match:
                match_count += 1
        else:
            _flush(current_file, current_lines, match_count)
            current_file = abs_path
            match_count = 1 if is_match else 0
            current_lines = [rebuilt]

    _flush(current_file, current_lines, match_count)

    files = []
    for fpath in file_order:
        group = file_groups[fpath]
        files.append(
            {
                "path": group["path"],
                "match_count": group["match_count"],
                "content": "\n".join(group["content_parts"]),
            }
        )
    return files


class Tool(BaseTool):
    NORM_NAME = "grep"
    RESULT_TYPE = "list"
    VALIDATIONS = {
        "searches[]": ["coerce_dict"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search for patterns in files. Supports multiple search operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "searches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pattern": {
                                    "type": "string",
                                    "description": "The pattern to search for.",
                                },
                                "file_glob": {
                                    "type": "string",
                                    "default": "*",
                                    "description": (
                                        "Glob pattern(s) for files to search. "
                                        "Comma-separated lists are supported; use ** for "
                                        "recursive matches and ! for ripgrep negation."
                                    ),
                                },
                                "directory": {
                                    "type": "string",
                                    "default": ".",
                                    "description": "Directory to search in.",
                                },
                                "use_regex": {
                                    "type": "boolean",
                                    "description": (
                                        "Whether to use regex search or literal text. "
                                        "Omit to auto-detect from the pattern and retry "
                                        "the other interpretation when one finds nothing."
                                    ),
                                },
                                "case_insensitive": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": (
                                        "Whether to perform a case-insensitive search "
                                        "(default true)."
                                    ),
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["files", "matches"],
                                    "default": "matches",
                                    "description": (
                                        "Output detail: 'files' lists paths and counts only, "
                                        "'matches' adds match lines (default). Set "
                                        "context_before/context_after to include surroundings."
                                    ),
                                },
                                "count": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": (
                                        "Whether to run a fast count pass for exact "
                                        "totals. When false, per-file totals are capped "
                                        f"at {MAX_LINE_NUMBERS} and may be approximate."
                                    ),
                                },
                                "context_before": {
                                    "type": "integer",
                                    "default": 0,
                                    "description": (
                                        "Number of context lines to show before each "
                                        f"match. Max {MAX_CONTEXT_LINES}; larger values "
                                        "are clamped with a warning."
                                    ),
                                },
                                "context_after": {
                                    "type": "integer",
                                    "default": 0,
                                    "description": (
                                        "Number of context lines to show after each "
                                        f"match. Max {MAX_CONTEXT_LINES}; larger values "
                                        "are clamped with a warning."
                                    ),
                                },
                            },
                            "required": ["pattern"],
                        },
                        "description": "Array of search operations to perform.",
                    }
                },
                "required": ["searches"],
            },
        },
    }

    @classmethod
    def _validate_backend(cls, tool_name, tool_path):
        """Test if a search backend actually works by running a quick check."""
        import subprocess

        if tool_name == "powershell":
            # PowerShell backend: verify the Select-String cmdlet is available.
            test_cmd = [
                tool_path,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "if (Get-Command Select-String -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }",
            ]
            try:
                result = subprocess.run(
                    test_cmd,
                    capture_output=True,
                    timeout=10,
                    text=True,
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                return False

        try:
            # Test with a simple pattern on a small known file
            test_cmd = [tool_path, "--version"]
            result = subprocess.run(
                test_cmd,
                capture_output=True,
                timeout=5,
                text=True,
            )
            # Check that it returns successfully AND produces output
            if result.returncode != 0:
                return False

            # Also do a quick search test on a small file to detect hangs
            grep_py = Path(__file__)
            if grep_py.exists() and grep_py.stat().st_size < 100000:
                search_test = [
                    tool_path,
                    "-c",
                    "-F",
                    "import",
                    "--",
                    str(grep_py),
                ]
                if tool_name == "rg":
                    # rg -r is --replace, not recursive. rg is recursive by default.
                    # Use -c for count mode with separate flags
                    search_test = [tool_path, "--count", "--fixed-strings", "import", str(grep_py)]
                elif tool_name == "ag":
                    search_test = [tool_path, "-c", "-Q", "import", str(grep_py)]
                else:
                    search_test = [tool_path, "-c", "-r", "-F", "import", str(grep_py)]

                result2 = subprocess.run(
                    search_test,
                    capture_output=True,
                    timeout=5,
                    text=True,
                )
                return result2.returncode in (0, 1)

            return True
        except (subprocess.TimeoutExpired, OSError, Exception):
            return False

    @classmethod
    def _find_search_tool(self):
        """Find the best available command-line search tool (rg, ag, grep, or PowerShell Select-String)."""
        candidates = ["rg", "ag", "grep", "powershell"]
        for name in candidates:
            if name == "powershell":
                # PowerShell (Select-String) is the Windows-native fallback.
                path = shutil.which("powershell") or shutil.which("pwsh")
            else:
                path = shutil.which(name)
            if not path:
                continue
            if self._validate_backend(name, path):
                return name, path
        return None, None

    @classmethod
    def execute(
        cls,
        coder,
        searches=None,
        **kwargs,
    ):
        """
        Search for lines matching patterns in files within the project repository.
        Uses rg (ripgrep), ag (the silver searcher), or grep, whichever is available.
        On Windows these may be absent, so PowerShell's Select-String is used as a fallback.
        Output is compact: paths are relative, lines are length-capped, and matches
        default to no surrounding context. Each search accepts a ``mode``:

        - ``"files"``: path and match count per file (skips the content pass)
        - ``"matches"`` (default): adds match line numbers and text; set
          ``context_before``/``context_after`` to include surrounding context lines

        Metadata carries exact totals plus per-file ``shown``/``truncated`` counts so
        location information survives even when content is truncated.
        """

        if not isinstance(searches, list):
            response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
            response.append_error("'searches' parameter must be an array.")
            return response

        repo = coder.repo
        if not repo:
            coder.io.tool_error("Not in a git repository.")
            response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
            response.append_error("Not in a git repository.")
            return response

        tool_name, tool_path = cls._find_search_tool()
        if not tool_path:
            coder.io.tool_error("No search tool (rg, ag, grep, powershell) found in PATH.")
            response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
            response.append_error("No search tool (rg, ag, grep, powershell) found.")
            return response

        all_operation_results = []

        for search_op in searches:
            pattern = strip_hashline(search_op.get("pattern", ""))
            file_pattern = search_op.get("file_glob", "*")
            directory = search_op.get("directory", search_op.get("path", "."))
            requested_regex = search_op.get("use_regex")
            use_regex = _should_use_regex(pattern, requested_regex)
            case_insensitive = search_op.get("case_insensitive", True)

            mode = search_op.get("mode", "matches")

            # Context is an orthogonal knob, disabled by default for compact output.
            context_before, context_before_warning = _parse_context_line_count(
                search_op.get("context_before", 0), "context_before"
            )
            context_after, context_after_warning = _parse_context_line_count(
                search_op.get("context_after", 0), "context_after"
            )
            count_enabled = search_op.get("count", True)

            op_result = {
                "pattern": pattern,
                "regex": use_regex,
                "mode": mode,
                "total_matches": 0,
                "total_files": 0,
                "has_more_files": False,
                "error": None,
            }

            context_warnings = [
                warning for warning in (context_before_warning, context_after_warning) if warning
            ]
            if context_warnings:
                _append_warnings(op_result, context_warnings)

            if mode not in ("files", "matches"):
                op_result["error"] = f"Invalid mode '{mode}'. Expected 'files' or 'matches'."
                all_operation_results.append(op_result)
                continue

            if not pattern:
                op_result["error"] = "Search operation requires a non-empty 'pattern'."
                all_operation_results.append(op_result)
                continue

            try:
                creator = is_creator_coder(coder)
                expanded_directory = Path(directory).expanduser()
                if creator and expanded_directory.is_absolute():
                    search_dir_path = expanded_directory
                else:
                    search_dir_path = Path(repo.root) / expanded_directory

                null_separated = tool_name in ("rg", "grep")

                if tool_name == "powershell":
                    # PowerShell (Select-String) backend: build a pipeline script and
                    # invoke it via -EncodedCommand to avoid shell quoting issues.
                    content_string = _encode_powershell_command(
                        _build_powershell_search_script(
                            search_dir_path=search_dir_path,
                            pattern=pattern,
                            file_pattern=file_pattern,
                            use_regex=use_regex,
                            case_insensitive=case_insensitive,
                            context_before=context_before,
                            context_after=context_after,
                            count_only=False,
                            exclude_cecli=not creator,
                        ),
                        tool_path,
                    )
                else:

                    def _build_commands(regex_enabled):
                        pattern_flag = []
                        if regex_enabled:
                            if tool_name == "grep":
                                pattern_flag = ["-P"] if _grep_supports_pcre(tool_path) else ["-E"]
                            elif tool_name == "rg" and _needs_pcre2(pattern):
                                pattern_flag = ["--pcre2"]
                        else:
                            if tool_name == "rg":
                                pattern_flag = ["-F"]
                            elif tool_name == "ag":
                                pattern_flag = ["-Q"]
                            elif tool_name == "grep":
                                pattern_flag = ["-F"]

                        # Case sensitivity
                        case_flag = ["-i"] if case_insensitive else []

                        # File filtering
                        file_filter = []
                        glob_patterns = _split_glob_patterns(file_pattern)
                        if glob_patterns != ["*"]:
                            if tool_name == "rg":
                                for glob_pattern in glob_patterns:
                                    file_filter.extend(["-g", glob_pattern])
                            elif tool_name == "ag":
                                for glob_pattern in glob_patterns:
                                    file_filter.extend(["-G", glob_pattern])
                            elif tool_name == "grep":
                                file_filter = ["-r"]
                                for glob_pattern in glob_patterns:
                                    file_filter.append(f"--include={glob_pattern}")
                        elif tool_name == "grep":
                            file_filter = ["-r"]

                        # Exclusions
                        exclude_args = []
                        _build_exclude_args(tool_name, exclude_args, exclude_cecli=not creator)

                        null_flag = []
                        if tool_name == "rg":
                            null_flag = ["--null"]
                        elif tool_name == "grep":
                            null_flag = ["-Z"]

                        # --- PASS1: Build count command (fast, no context) ---
                        count_cmd_parts = [tool_path]
                        if tool_name == "rg":
                            count_cmd_parts.extend(["-c", "--no-config"])
                        elif tool_name == "ag":
                            count_cmd_parts.append("-rc")
                        else:
                            # -I skips binary files, matching the content pass.
                            count_cmd_parts.extend(["-rnc", "-I"])
                        count_cmd = (
                            count_cmd_parts
                            + case_flag
                            + pattern_flag
                            + file_filter
                            + exclude_args
                            + null_flag
                            + ["--", pattern, str(search_dir_path)]
                        )
                        count_string = oslex.join(count_cmd)

                        # Source-level caps: bound matches per file and line length so
                        # post-processing never sees unbounded content.
                        output_cap_args = []
                        if tool_name == "rg":
                            output_cap_args = [
                                "-m",
                                str(MAX_LINE_NUMBERS),
                                "--max-columns",
                                str(MAX_LINE_LENGTH),
                                "--max-columns-preview",
                            ]
                        elif tool_name == "grep":
                            # -I skips binary files; -m bounds matches per file.
                            output_cap_args = ["-I", "-m", str(MAX_LINE_NUMBERS)]

                        # --- PASS2: Build content with context ---
                        base_cmd = [tool_path, "-n"]
                        if tool_name == "rg":
                            base_cmd.extend(
                                [
                                    "--with-filename",
                                    "--no-heading",
                                    "--color=never",
                                    "--no-config",
                                ]
                            )

                        content_cmd = (
                            base_cmd
                            + output_cap_args
                            + null_flag
                            + (["-B", str(context_before)] if context_before > 0 else [])
                            + (["-A", str(context_after)] if context_after > 0 else [])
                            + case_flag
                            + pattern_flag
                            + file_filter
                            + exclude_args
                            + ["--", pattern, str(search_dir_path)]
                        )
                        content_string = oslex.join(content_cmd)

                        return count_string, content_string

                    count_string, content_string = _build_commands(use_regex)

                # --- PASS1: Get match counts (fast, no context) ---
                counts = {}
                count_status = 0
                count_output = ""
                if count_enabled and tool_name != "powershell":
                    coder.io.tool_output(
                        f"⛭ Counting matches with {tool_name}: '{pattern}' in {directory}",
                        type="tool-result",
                    )
                    count_status, count_output = run_cmd_subprocess(
                        count_string,
                        verbose=coder.verbose,
                        cwd=coder.root,
                        should_print=False,
                    )
                    if count_status in (0, 1, 2):
                        counts = _parse_count_output(count_output, null_separated=null_separated)

                    # Auto mode retries the other interpretation when one comes back
                    # empty or invalid. This is what makes unescaped regex syntax work
                    # without turning ordinary literal patterns into regexes.
                    should_try_alternate = False
                    if requested_regex is None and not counts and _has_regex_meta(pattern):
                        should_try_alternate = True
                    elif requested_regex is True and not counts and count_status == 2:
                        should_try_alternate = True

                    if should_try_alternate:
                        alternate_regex = not use_regex
                        alternate_count_string, alternate_content_string = _build_commands(
                            alternate_regex
                        )
                        alternate_status, alternate_output = run_cmd_subprocess(
                            alternate_count_string,
                            verbose=coder.verbose,
                            cwd=coder.root,
                            should_print=False,
                        )
                        alternate_counts = {}
                        if alternate_status in (0, 1, 2):
                            alternate_counts = _parse_count_output(
                                alternate_output, null_separated=null_separated
                            )

                        if alternate_counts or (not alternate_regex and alternate_status in (0, 1)):
                            use_regex = alternate_regex
                            counts = alternate_counts
                            count_status = alternate_status
                            count_output = alternate_output
                            count_string = alternate_count_string
                            content_string = alternate_content_string
                            op_result["regex"] = use_regex

                            if requested_regex is True:
                                _append_warnings(
                                    op_result,
                                    ["Regex search failed; retried as a literal string."],
                                )

                if count_status == 2 and null_separated:
                    count_warnings = _extract_warnings(count_output, null_separated=True)
                    if count_warnings:
                        _append_warnings(op_result, count_warnings)

                # "files" mode only needs counts, so skip the content pass entirely.
                if mode == "files" and counts:
                    rel_files = []
                    for raw_path, file_count in counts.items():
                        abs_path = (
                            raw_path
                            if os.path.isabs(raw_path)
                            else os.path.normpath(os.path.join(repo.root, raw_path))
                        )
                        rel_files.append((safe_relpath(abs_path, repo.root), file_count))
                    rel_files.sort(key=lambda item: (-item[1], item[0]))

                    shown_files = rel_files[:MAX_FILES]
                    op_result["total_matches"] = sum(count for _, count in rel_files)
                    op_result["total_files"] = len(rel_files)
                    op_result["has_more_files"] = len(rel_files) > MAX_FILES
                    op_result["_lines"] = [
                        {
                            "file": rel_path,
                            "match_count": file_count,
                            "lines": [f"{rel_path}: {file_count}"],
                        }
                        for rel_path, file_count in shown_files
                    ]
                    all_operation_results.append(op_result)
                    continue

                # --- PASS2: Get content with context ---
                coder.io.tool_output(
                    f"⛭ Executing {tool_name}: '{pattern}' in {directory}",
                    type="tool-result",
                )
                content_status, content_output = run_cmd_subprocess(
                    content_string,
                    verbose=coder.verbose,
                    cwd=coder.root,
                    should_print=False,
                )

                output_content = content_output or ""

                parsed_files = []
                if output_content:
                    if tool_name == "powershell":
                        parsed_files = _parse_select_string_output(output_content, repo.root)
                    else:
                        parsed_files = _parse_content_into_files(
                            output_content, null_separated=null_separated
                        )

                if content_status == 2 and parsed_files:
                    content_warnings = _extract_warnings(
                        output_content, null_separated=null_separated
                    )
                    if content_warnings:
                        _append_warnings(op_result, content_warnings)

                if parsed_files:

                    # Merge in counts from pass 1 if available
                    if counts:
                        for pf in parsed_files:
                            raw_path = pf["path"]
                            if raw_path in counts:
                                pf["count_from_pass"] = counts[raw_path]
                            else:
                                # Try with repo root prefix stripped
                                rel = safe_relpath(raw_path, repo.root)
                                pf["count_from_pass"] = counts.get(rel, pf["match_count"])
                    else:
                        for pf in parsed_files:
                            pf["count_from_pass"] = pf["match_count"]

                    # Build compact per-file output: relative paths, match lines with
                    # optional context (context_before/context_after), and capped lengths.
                    total_matches = 0
                    total_files = len(parsed_files)
                    has_more = total_files > MAX_FILES

                    rendered = []
                    count_capped = False
                    for pf in parsed_files[:MAX_FILES]:
                        rel_path = safe_relpath(pf["path"], repo.root)
                        count = pf.get("count_from_pass", 0)
                        total_matches += count

                        entries = _extract_file_entries(pf["path"], pf["content"])
                        matches = [entry for entry in entries if entry["is_match"]]
                        extra_line_numbers = [
                            entry["line"] for entry in matches[MAX_MATCHES_PER_FILE:]
                        ][:MAX_ADDITIONAL_LINE_NUMBERS]

                        count_capped_here = False
                        if mode == "files":
                            lines = [f"{rel_path}: {count}"]
                            if not count_enabled and len(matches) >= MAX_LINE_NUMBERS:
                                count_capped = True
                                count_capped_here = True
                            match_seen = 0
                        else:
                            lines = [f"{rel_path}: {count} match(es)"]
                            match_seen = 0
                            for entry in entries:
                                if entry["is_match"]:
                                    if match_seen >= MAX_MATCHES_PER_FILE:
                                        break
                                    match_seen += 1
                                    marker = ":"
                                else:
                                    marker = "-"
                                lines.append(
                                    f"  {entry['line']}{marker} {_cap_line(entry['text'])}"
                                )

                            if not count_enabled and len(matches) >= MAX_LINE_NUMBERS:
                                count_capped = True
                                count_capped_here = True

                        shown_count = match_seen if mode == "matches" else 0
                        truncated = mode == "matches" and count > shown_count
                        if truncated:
                            lines.append(f" … showing {shown_count} of {count} matches")
                            if extra_line_numbers:
                                extra = ", ".join(str(num) for num in extra_line_numbers)
                                lines.append(f" … +{count - shown_count} more locations: {extra}")
                        if count_capped_here:
                            lines.append(f" … count capped at {MAX_LINE_NUMBERS} per file")

                        item = {
                            "file": rel_path,
                            "match_count": count,
                            "lines": lines,
                        }
                        if shown_count:
                            item["shown"] = shown_count
                        if truncated:
                            item["truncated"] = True
                        if extra_line_numbers:
                            item["additional_line_numbers"] = extra_line_numbers
                        rendered.append(item)

                    if has_more:
                        for pf in parsed_files[MAX_FILES:]:
                            total_matches += pf.get("count_from_pass", 0)

                    if count_capped:
                        _append_warnings(
                            op_result,
                            [
                                "count=false: per-file totals are capped at "
                                f"{MAX_LINE_NUMBERS}; enable count for exact totals."
                            ],
                        )

                    # Byte-aware eviction: drop the largest blocks until under budget so
                    # a single pathological file cannot crowd out many small ones.
                    files_omitted_for_size = 0
                    while rendered and (
                        sum(len("\n".join(item["lines"])) + 1 for item in rendered) > MAX_TOTAL_SIZE
                    ):
                        largest = max(rendered, key=lambda item: len("\n".join(item["lines"])))
                        rendered.remove(largest)
                        files_omitted_for_size += 1

                    if files_omitted_for_size:
                        has_more = True
                        op_result["files_omitted_for_size"] = files_omitted_for_size

                    op_result["total_matches"] = total_matches
                    op_result["total_files"] = total_files
                    op_result["has_more_files"] = has_more
                    op_result["_lines"] = rendered

                elif content_status in (0, 1) or not output_content:
                    op_result["total_matches"] = 0
                    op_result["total_files"] = 0
                    if output_content:
                        content_warnings = _extract_warnings(
                            output_content, null_separated=null_separated
                        )
                        if content_warnings:
                            _append_warnings(op_result, content_warnings)
                else:
                    op_result["error"] = output_content

            except Exception as e:
                op_result["error"] = f"Error executing search: {str(e)}"

            if (
                op_result.get("total_matches", 0) == 0
                and not op_result.get("error")
                and file_pattern
                and file_pattern != "*"
            ):
                _append_warnings(
                    op_result,
                    [
                        f"No matches with file_glob={file_pattern!r}; "
                        "verify the glob matches files (comma lists are supported)."
                    ],
                )

            all_operation_results.append(op_result)

        # Cap total output across operations, dropping the largest rendered blocks
        # first so one pathological file cannot crowd out many small, useful ones.
        while (
            sum(
                len("\n".join(item["lines"])) + 1
                for op in all_operation_results
                for item in op.get("_lines", [])
            )
            > MAX_TOTAL_SIZE
        ):
            largest_size = -1
            largest_op = None
            largest_idx = -1
            for op in all_operation_results:
                for idx, item in enumerate(op.get("_lines", [])):
                    size = len("\n".join(item["lines"])) + 1
                    if size > largest_size:
                        largest_size = size
                        largest_op = op
                        largest_idx = idx

            if largest_op is None:
                break

            largest_op["_lines"].pop(largest_idx)
            largest_op["has_more_files"] = True
            largest_op["files_omitted_for_size"] = largest_op.get("files_omitted_for_size", 0) + 1

        for op_result in all_operation_results:
            omitted = op_result.get("files_omitted_for_size", 0)
            if omitted:
                _append_warnings(
                    op_result,
                    [
                        f"{omitted} file result block(s) omitted to stay within "
                        f"the {MAX_TOTAL_SIZE} byte output budget."
                    ],
                )

        # TUI summary
        if coder.tui and coder.tui():
            ui_summaries = []
            for op in all_operation_results:
                pattern = op["pattern"]
                if op["error"]:
                    ui_summaries.append(f"✗ Error searching for '{pattern}': {op['error']}")
                elif op["total_matches"] == 0:
                    ui_summaries.append(f"✗ No matches found for '{pattern}'.")
                else:
                    ui_summaries.append(
                        f"✓ '{pattern}': {op['total_matches']} matches in "
                        f"{op['total_files']} files"
                    )
            ui_message = "\n".join(ui_summaries)
            coder.io.tool_output(ui_message, type="tool-result")

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
        for op_result in all_operation_results:
            pattern = op_result.get("pattern", "")
            pattern_label = pattern or "<empty>"

            if op_result.get("error"):
                body = [
                    f"[{pattern_label}]",
                    f"Error: {_cap_line(str(op_result['error']).strip(), 1000)}",
                ]
            elif op_result.get("total_matches", 0) == 0:
                body = [f"[{pattern_label}]", "No matches found."]
            else:
                body = [f"[{pattern_label}]"]
                for item in op_result.get("_lines", []):
                    body.extend(item["lines"])
                if op_result.get("has_more_files"):
                    body.append(
                        f"... ({op_result['total_files']} files total, "
                        f"showing {len(op_result.get('_lines', []))})"
                    )

            warnings = op_result.get("warnings", [])
            if op_result.get("error"):
                warnings = [
                    warning for warning in warnings if warning not in str(op_result["error"])
                ]
            if warnings:
                op_result["warnings"] = warnings
            else:
                op_result.pop("warnings", None)

            for warning in warnings[:5]:
                body.append(f"Warning: {_cap_line(warning)}")
            metadata = {key: value for key, value in op_result.items() if key != "_lines"}
            response.append_result(content="\n".join(body), metadata=metadata)

        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format the search parameters for TUI display."""
        color_start, color_end = color_markers(coder)

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        # Display each search operation
        searches = params.get("searches", [])
        if searches:
            coder.io.tool_output("")
            for i, search_op in enumerate(searches):
                pattern = search_op.get("pattern", "")
                file_pattern = search_op.get("file_glob", "*")
                directory = search_op.get("directory", search_op.get("path", "."))
                use_regex = _should_use_regex(pattern, search_op.get("use_regex"))
                case_insensitive = search_op.get("case_insensitive", True)
                mode = search_op.get("mode", "matches")
                context_before, _ = _parse_context_line_count(
                    search_op.get("context_before", 0), "context_before"
                )
                context_after, _ = _parse_context_line_count(
                    search_op.get("context_after", 0), "context_after"
                )

                formatted_query = (
                    f"{color_start}search_{i + 1}:{color_end} {pattern} • {file_pattern} •"
                    f" {directory}"
                )
                options = []
                if mode != "matches":
                    options.append(mode)
                if use_regex:
                    options.append("regex")
                if case_insensitive:
                    options.append("case-insensitive")
                if context_before or context_after:
                    options.append(f"context:{context_before}/{context_after}")
                if options:
                    formatted_query += f" • {' '.join(options)}"
                coder.io.tool_output(formatted_query)

            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
