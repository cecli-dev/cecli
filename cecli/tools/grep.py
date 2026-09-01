import base64
import os
import re
import shutil
from pathlib import Path

import oslex

from cecli.helpers.hashline import strip_hashline
from cecli.run_cmd import run_cmd_subprocess
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations

# Default directories to exclude from search results across various languages
DEFAULT_EXCLUDE_DIRS = [
    ".git",
    ".cecli",
    ".venv",
    "venv",
    "env",
    ".env",
    "__pycache__",
    "*.pyc",
    "node_modules",
    "bower_components",
    ".next",
    "dist",
    "build",
    "target",  # Rust / Java / Kotlin
    "bin",
    "obj",  # C# / .NET
    ".gradle",  # Java/Kotlin
    ".mvn",
    "vendor",  # Go / PHP
    ".bundle",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".eggs",
    "eggs",
    "lib",
    "lib64",
    ".dub",  # D
    "dub.selections.json",
    "Pods",  # CocoaPods
    ".build",  # Swift
    ".cargo",  # Rust
]


def _build_exclude_args(tool_name, cmd_args):
    """Add exclusion arguments for common build/artifact directories."""
    for exclude_dir in DEFAULT_EXCLUDE_DIRS:
        if tool_name == "rg":
            cmd_args.extend(["-g", f"!{exclude_dir}"])
        elif tool_name == "ag":
            cmd_args.extend(["--ignore-dir", exclude_dir])
        elif tool_name == "grep":
            cmd_args.extend(["--exclude-dir", exclude_dir])
    return cmd_args


def _parse_count_output(output):
    """Parse grep -c output (file:count per line) into a dict."""
    counts = {}
    if not output:
        return counts
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: filepath:count
        # Use rsplit to handle paths that may contain colons
        idx = line.rfind(":")
        if idx > 0:
            filepath = line[:idx]
            try:
                count_val = int(line[idx + 1 :])
                counts[filepath] = count_val
            except (ValueError, IndexError):
                pass
    return counts


def _parse_content_into_files(output):
    """Parse grep -rn output into per-file groups.

    Returns list of dicts with keys: path, match_count, content_lines
    Content lines preserve the original grep format (with : for matches, - for context).
    Merges entries for the same file that appear in non-contiguous match groups.
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

        # Try to extract filename from the line prefix
        # Match lines:   path:line:content
        # Context lines: path-line-content  (with - hyphen after line number)
        m = re.match(r"^(.+?)[:-](\d+)[:-]", line)
        if m:
            filepath = m.group(1)
            # Actually check: match lines have :LINE:, context lines have -LINE-
            # The format is: path:line:content or path-line-content
            # Check whether the char after line num is : or -
            line_num_end = len(filepath) + 1 + len(m.group(2))
            is_match_line = line_num_end < len(line) and line[line_num_end] == ":"

            if current_file is None:
                current_file = filepath
                match_count = 1 if is_match_line else 0
                current_lines = [line]
            elif filepath == current_file:
                current_lines.append(line)
                if is_match_line:
                    match_count += 1
            else:
                # Different file - flush current block before switching
                _flush_current()
                current_file = filepath
                match_count = 1 if is_match_line else 0
                current_lines = [line]
        else:
            # Line that doesn't match the pattern (e.g. rg --heading output)
            if current_file is not None:
                current_lines.append(line)

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


def _build_powershell_exclude_regex(exclude_dirs=None):
    """Build a PowerShell -notmatch regex that skips default build/artifact dirs."""
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDE_DIRS
    fragments = []
    for entry in exclude_dirs:
        # Escape the literal text, then turn * globs into path-segment wildcards.
        frag = re.escape(entry).replace(r"\*", r"[^\\/]*")
        fragments.append(frag)
    if not fragments:
        return None
    return r"(?:\\|/)(?:" + "|".join(fragments) + r")(?:\\|/|$)"


def _build_powershell_search_script(
    search_dir_path,
    pattern,
    file_pattern,
    use_regex,
    case_insensitive,
    context_before,
    context_after,
    count_only,
):
    """Build a PowerShell pipeline that mimics rg/ag/grep via Select-String."""

    def _ps_quote(value):
        # Embed a value in a PowerShell single-quoted string ('' escapes a quote).
        return "'" + str(value).replace("'", "''") + "'"

    parts = ["Get-ChildItem", "-LiteralPath", _ps_quote(search_dir_path), "-Recurse", "-File"]

    if file_pattern != "*":
        parts.extend(["-Filter", _ps_quote(file_pattern)])

    exclude_regex = _build_powershell_exclude_regex()
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
                                    "description": "Glob pattern for files to search.",
                                },
                                "directory": {
                                    "type": "string",
                                    "default": ".",
                                    "description": "Directory to search in.",
                                },
                                "use_regex": {
                                    "type": "boolean",
                                    "default": False,
                                    "description": "Whether to use regex.",
                                },
                                "case_insensitive": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": "Whether to perform a case-insensitive search.",
                                },
                                "context_before": {
                                    "type": "integer",
                                    "default": 2,
                                    "description": (
                                        "Number of context lines to show before each match. Max 5"
                                    ),
                                },
                                "context_after": {
                                    "type": "integer",
                                    "default": 2,
                                    "description": (
                                        "Number of context lines to show after each match. Max 5"
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
        Returns a JSON string with structured results including per-file groupings,
        match counts, and summary metadata.
        """
        import json

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
            use_regex = search_op.get("use_regex", False)
            case_insensitive = search_op.get("case_insensitive", True)
            context_before = max(min(int(search_op.get("context_before", 2)), 5), 0)
            context_after = max(min(int(search_op.get("context_after", 2)), 5), 0)
            count_enabled = search_op.get("count", True)

            op_result = {
                "pattern": pattern,
                "file_glob": file_pattern,
                "directory": directory,
                "use_regex": use_regex,
                "case_insensitive": case_insensitive,
                "count": count_enabled,
                "context_before": context_before,
                "context_after": context_after,
                "total_matches": 0,
                "total_files": 0,
                "has_more_files": False,
                "error": None,
                "files": [],
            }

            if not pattern:
                op_result["error"] = "Search operation requires a non-empty 'pattern'."
                all_operation_results.append(op_result)
                continue

            try:
                search_dir_path = Path(repo.root) / directory

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
                        ),
                        tool_path,
                    )
                else:
                    # Build base content command
                    base_cmd = [tool_path, "-n"]
                    if tool_name == "rg":
                        base_cmd.append("--with-filename")

                    # Pattern type
                    pattern_flag = []
                    if use_regex:
                        if tool_name == "grep":
                            pattern_flag = ["-E"]
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
                    if file_pattern != "*":
                        if tool_name == "rg":
                            file_filter = ["-g", file_pattern]
                        elif tool_name == "ag":
                            file_filter = ["-G", file_pattern]
                        elif tool_name == "grep":
                            file_filter = ["-r", f"--include={file_pattern}"]
                    elif tool_name == "grep":
                        file_filter = ["-r"]

                    # Exclusions
                    exclude_args = []
                    _build_exclude_args(tool_name, exclude_args)

                    # --- PASS1: Build count command (fast, no context) ---
                    count_cmd_parts = [tool_path]
                    if tool_name == "rg":
                        count_cmd_parts.append("-c")
                    elif tool_name == "ag":
                        count_cmd_parts.append("-rc")
                    else:
                        count_cmd_parts.append("-rnc")
                    count_cmd = (
                        count_cmd_parts
                        + case_flag
                        + pattern_flag
                        + exclude_args
                        + file_filter
                        + ["--", pattern, str(search_dir_path)]
                    )
                    count_string = oslex.join(count_cmd)

                    # --- PASS2: Build content with context ---
                    content_cmd = (
                        base_cmd
                        + (["-B", str(context_before)] if context_before >= 0 else [])
                        + (["-A", str(context_after)] if context_after >= 0 else [])
                        + case_flag
                        + pattern_flag
                        + exclude_args
                        + file_filter
                        + ["--", pattern, str(search_dir_path)]
                    )
                    content_string = oslex.join(content_cmd)

                # --- PASS1: Get match counts (fast, no context) ---
                counts = {}
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
                    if count_status == 0:
                        counts = _parse_count_output(count_output)

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

                if content_status == 0 and output_content:
                    if tool_name == "powershell":
                        parsed_files = _parse_select_string_output(output_content, repo.root)
                    else:
                        parsed_files = _parse_content_into_files(output_content)

                    # Merge in counts from pass 1 if available
                    if counts:
                        for pf in parsed_files:
                            raw_path = pf["path"]
                            if raw_path in counts:
                                pf["count_from_pass"] = counts[raw_path]
                            else:
                                # Try with repo root prefix stripped
                                rel = os.path.relpath(raw_path, repo.root)
                                pf["count_from_pass"] = counts.get(rel, pf["match_count"])
                    else:
                        for pf in parsed_files:
                            pf["count_from_pass"] = pf["match_count"]

                    # Apply file-based truncation:
                    MAX_MATCHES_PER_FILE = 10
                    MAX_FILES = 20

                    truncated_files = {}
                    total_matches = 0
                    total_files = 0

                    for pf in parsed_files[:MAX_FILES]:
                        file_lines = pf["content"].splitlines()
                        # Find actual match lines (lines with `:LINE:` pattern)
                        filepath_escaped = re.escape(pf["path"])
                        match_line_re = re.compile(r"^(?:> )?" + filepath_escaped + r":(\d+):")
                        match_lines_found = [ln for ln in file_lines if match_line_re.match(ln)]

                        # Normalize path to be relative to repo root
                        pf["path"] = os.path.relpath(pf["path"], repo.root)

                        if len(match_lines_found) > MAX_MATCHES_PER_FILE:
                            # Extract line numbers from excess matches (beyond first 10)
                            extra_lines = match_lines_found[MAX_MATCHES_PER_FILE:]
                            extra_line_nums = []
                            for xline in extra_lines:
                                xm = match_line_re.match(xline)
                                if xm:
                                    extra_line_nums.append(int(xm.group(1)))
                            truncated_files[pf["path"]] = extra_line_nums
                            trimmed = "\n".join(match_lines_found[:MAX_MATCHES_PER_FILE])
                            pf["content"] = trimmed
                        total_matches += pf.get("count_from_pass", 0)
                        total_files += 1

                    has_more = len(parsed_files) > MAX_FILES
                    if has_more:
                        for pf in parsed_files[MAX_FILES:]:
                            total_matches += pf.get("count_from_pass", 0)
                            total_files += 1

                    op_result["total_matches"] = total_matches
                    op_result["total_files"] = total_files
                    op_result["has_more_files"] = has_more
                    op_result["files"] = [
                        {
                            "file": pf["path"],
                            "match_count": pf.get("count_from_pass", 0),
                            "additional_matched_lines": truncated_files.get(pf["path"], []),
                            "content": pf["content"],
                        }
                        for pf in parsed_files[:MAX_FILES]
                    ]

                elif content_status == 1 or not output_content:
                    op_result["total_matches"] = 0
                    op_result["total_files"] = 0
                else:
                    op_result["error"] = output_content

            except Exception as e:
                op_result["error"] = f"Error executing search: {str(e)}"

            all_operation_results.append(op_result)

        # Cap the output size to 50k characters for the LLM
        # Heuristic: Prioritize shallowness (short paths) and fewer matches
        # Removal order: Longest paths first, then most matches first.
        MAX_TOTAL_SIZE = 50000
        if len(json.dumps(all_operation_results)) > MAX_TOTAL_SIZE:
            # Flatten files with their metadata for sorting
            all_files_to_rank = []
            for op_idx, op in enumerate(all_operation_results):
                for file_idx, f_data in enumerate(op.get("files", [])):
                    all_files_to_rank.append(
                        {
                            "op_idx": op_idx,
                            "file_idx": file_idx,
                            "path_len": len(f_data.get("file", "")),
                            "match_count": f_data.get("match_count", 0),
                        }
                    )

            # Sort for REMOVAL (worst first): Longest path, then most matches
            all_files_to_rank.sort(key=lambda x: (x["path_len"], x["match_count"]), reverse=True)

            # Progressively remove files until under limit
            removed_set = set()
            trimmed_results = all_operation_results
            for rank_info in all_files_to_rank:
                removed_set.add((rank_info["op_idx"], rank_info["file_idx"]))

                # Reconstruct to check size
                trimmed_results = []
                for o_idx, op in enumerate(all_operation_results):
                    new_op = op.copy()
                    original_files = op.get("files", [])
                    new_op["files"] = [
                        f
                        for f_idx, f in enumerate(original_files)
                        if (o_idx, f_idx) not in removed_set
                    ]
                    if len(new_op["files"]) < len(original_files):
                        new_op["has_more_files"] = True
                    trimmed_results.append(new_op)

                if len(json.dumps(trimmed_results)) <= MAX_TOTAL_SIZE:
                    all_operation_results = trimmed_results
                    break
            else:
                all_operation_results = trimmed_results

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
            files = op_result.get("files", [])
            metadata = op_result.copy()

            # Build a human-readable string summary as content
            pattern = op_result.get("pattern", "")
            if op_result.get("error"):
                summary = f"[{pattern}]\nError: {op_result['error']}"
            elif op_result.get("total_matches", 0) == 0:
                summary = f"[{pattern}]\nNo matches found."
            else:
                lines = [f"[{pattern}]"]
                for f in files:
                    truncated_mark = " (truncated)" if f.get("additional_matched_lines") else ""
                    lines.append(f"{f['file']}: {f['match_count']} match(es){truncated_mark}")
                if op_result.get("has_more_files"):
                    lines.append(f"... ({op_result['total_files']} files total)")
                summary = "\n".join(lines)

            response.append_result(content=summary, metadata=metadata)

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
                use_regex = search_op.get("use_regex", False)
                case_insensitive = search_op.get("case_insensitive", True)
                context_before = search_op.get("context_before", 2)
                context_after = search_op.get("context_after", 2)

                formatted_query = (
                    f"{color_start}search_{i + 1}:{color_end} {pattern} • {file_pattern} •"
                    f" {directory}"
                )
                options = []
                if use_regex:
                    options.append("regex")
                if case_insensitive:
                    options.append("case-insensitive")
                if context_before != 2 or context_after != 2:
                    options.append(f"context:{context_before}/{context_after}")
                if options:
                    formatted_query += f" • {' '.join(options)}"
                coder.io.tool_output(formatted_query)

            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
