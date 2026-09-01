"""
Singleton-like proxy injected into the orchestration environment.

Usage in LLM-generated code:

    read_tool = Agent.get_tool("ReadFile")
    result = await read_tool.call(file_path="foo.py", range_start="@000", range_end="000@")

Supports both local tools (from ToolRegistry) and MCP tools (from connected
servers) using `ServerName--ToolName` or bare tool-name lookup.
"""

from __future__ import annotations

from typing import Any

from cecli.helpers import nested, responses
from cecli.helpers.orchestration.tool_proxy import ToolProxy


class AgentProxy:
    """
    Singleton-like proxy injected into the orchestration environment.

    Usage in LLM-generated code:

        read_tool = Agent.get_tool("ReadFile")
        result = await read_tool.call(file_path="foo.py", range_start="@000", range_end="000@")

    Supports both local tools (from ToolRegistry) and MCP tools (from connected
    servers) using `ServerName--ToolName` or bare tool-name lookup.
    """

    def __init__(self, coder: Any) -> None:
        self._coder = coder
        self._env = None  # Set by AgentExecutionEnv after creation

    def get_tool(self, tool_name: str) -> ToolProxy:
        from cecli.tools.utils.registry import ToolRegistry

        name_lower = tool_name.lower()

        # 1. Try local tools by exact name (unprefixed)
        tool_module = ToolRegistry.get_tool(name_lower)
        if tool_module is not None:
            return ToolProxy(tool_name, self._coder, tool_module=tool_module)

        # 2. Unprefix: "ServerName--ToolName" → (server_prefix, bare_name)
        server_prefix, bare_name = responses.unprefix_tool_name(name_lower)

        # 3. If the prefix is "local", retry ToolRegistry with the bare name
        if server_prefix == "local" and bare_name:
            tool_module = ToolRegistry.get_tool(bare_name)
            if tool_module is not None:
                return ToolProxy(tool_name, self._coder, tool_module=tool_module)
            # Also try with hyphen normalization on the bare name
            bare_underscored = bare_name.replace("-", "_")
            if bare_underscored != bare_name:
                tool_module = ToolRegistry.get_tool(bare_underscored)
                if tool_module is not None:
                    return ToolProxy(tool_name, self._coder, tool_module=tool_module)

        # 3b. Replace hyphens with underscores and retry (kebab-case -> snake_case)
        underscored = name_lower.replace("-", "_")
        if underscored != name_lower:
            tool_module = ToolRegistry.get_tool(underscored)
            if tool_module is not None:
                return ToolProxy(tool_name, self._coder, tool_module=tool_module)

        # 3c. Strip underscores from the tool name and retry (snake_case fallback)
        no_underscore = name_lower.replace("_", "")
        if no_underscore != name_lower:
            tool_module = ToolRegistry.get_tool(no_underscore)
            if tool_module is not None:
                return ToolProxy(tool_name, self._coder, tool_module=tool_module)

        # 4. Search MCP tools for the bare (unprefixed) name
        for mcp_server_name, server_tools in self._coder.mcp_tools or []:
            for tool_schema in server_tools:
                schema_name = nested.getter(tool_schema, "function.name", "")
                _schema_prefix, schema_unprefixed = responses.unprefix_tool_name(
                    schema_name.lower()
                )
                if schema_unprefixed == bare_name:
                    server = self._find_mcp_server(mcp_server_name, server_prefix)
                    if server is not None:
                        return ToolProxy(
                            tool_name,
                            self._coder,
                            mcp_server=server,
                            mcp_tool_name=schema_name,
                        )

        raise ValueError(f"Unknown tool: '{tool_name}'")

    def _find_mcp_server(self, server_name: str, server_prefix: str) -> Any:
        if not hasattr(self._coder, "mcp_manager") or not self._coder.mcp_manager:
            return None
        for server in self._coder.mcp_manager:
            if server.name == server_name and (
                not server_prefix or server.name.lower() == server_prefix.lower()
            ):
                return server
        return None

    def peek(self, result: Any) -> str:
        """Inspect the structure of a tool result and return a readable summary.

        Tool results have a standard shape:

            {
                "result": [{"content": ..., "_": {"file_path": ..., ...}}],
                "errors": [...],
                "details": [...]
            }

        This method unwraps the structure to show what keys are available,
        helping the LLM navigate deeply nested tool outputs.  Leaf values
        include a short content snippet so you can see actual data.

        Example:

            output = await grep_tool.call(pattern="TODO", file_glob="*.py")
            print(Agent.peek(output))
            # Shows: result[0].content: str = 'def foo():...'
            #        result[0]._.file_path: str = 'src/main.py'

            # Now the LLM can confidently access:
            for item in output["result"]:
                print(item["content"])  # or item["_"]["file_path"]

        Returns a multi-line string describing the available access paths
        with short content previews for leaf values.
        """

        return self._inspect_structure(result)

    def get_value(self, result: Any, path: str, default: Any = None) -> Any:
        """Safely access nested values in a tool result using dot-notation.

        Tool results have deeply nested dicts (e.g., ``result["result"][0]["_"]["file_path"]``).
        ``get_value()`` provides a concise shorthand using ``nested.getter()``.

        Example:

            output = await grep_tool.call(pattern="TODO", file_glob="*.py")
            file_path = Agent.get_value(output, "result.0._.file_path")
            content = Agent.get_value(output, "result.0.content")

        Returns *default* if the path does not exist.
        """
        from cecli.helpers import nested

        # SECURITY: Reject paths that access private/dunder attributes
        # (unless disable_security is active)
        if not (self._env and self._env._orchestration_config.get("disable_security", False)):
            for segment in path.replace("[", ".").replace("]", "").split("."):
                segment = segment.strip()
                if segment.startswith("_") and segment != "_":
                    from cecli.helpers.orchestration.security import SecurityError

                    raise SecurityError(f"Access to private attribute '{segment}' is forbidden")

        return nested.getter(result, path, default)

    @staticmethod
    def _content_preview(value: Any, max_chars: int = 20) -> str:
        """Return a short preview of a scalar value's stringified content."""

        s = str(value)
        if len(s) <= max_chars:
            return repr(s)

        return repr(s[:max_chars]) + "..."

    @staticmethod
    def _inspect_structure(obj: Any, prefix: str = "", depth: int = 0) -> str:
        """Recursively inspect the structure of a tool result — paths, types, and content previews."""

        max_depth = 3
        max_keys = 5
        lines: list[str] = []

        if depth > max_depth:
            return ""

        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    keys = list(value.keys())[:max_keys]
                    suffix = "..." if len(value) > max_keys else ""
                    lines.append(f"{path}: dict[{' | '.join(keys)}{suffix}]")
                    inner = AgentProxy._inspect_structure(value, path, depth + 1)
                    if inner:
                        lines.append(inner)
                elif isinstance(value, list):
                    if value:
                        first = value[0]
                        if isinstance(first, dict):
                            lines.append(f"{path}: list[{len(value)}] dict")
                            inner = AgentProxy._inspect_structure(first, f"{path}[0]", depth + 1)
                            if inner:
                                lines.append(inner)
                        else:
                            lines.append(f"{path}: list[{len(value)}] {type(first).__name__}")
                    else:
                        lines.append(f"{path}: list (empty)")
                elif (
                    hasattr(value, "keys")
                    and hasattr(value, "items")
                    and not isinstance(value, (str, bytes))
                ):
                    sub_keys = list(value.keys())[:max_keys]
                    sub_suffix = "..." if len(value) > max_keys else ""
                    lines.append(
                        f"{path}: {type(value).__name__}(keys: [{', '.join(sub_keys)}{sub_suffix}])"
                    )
                    inner = AgentProxy._inspect_structure(value, path, depth + 1)
                    if inner:
                        lines.append(inner)
                else:
                    preview = AgentProxy._content_preview(value)
                    lines.append(f"{path}: {type(value).__name__} = {preview}")

        elif isinstance(obj, list):
            if obj:
                first = obj[0]
                if isinstance(first, dict):
                    lines.append(f"list[{len(obj)}] dict")
                    inner = AgentProxy._inspect_structure(
                        first, f"{prefix}[0]" if prefix else "[0]", depth + 1
                    )
                    if inner:
                        lines.append(inner)
                else:
                    lines.append(f"list[{len(obj)}] {type(first).__name__}")
            else:
                lines.append("list (empty)")

        elif hasattr(obj, "keys") and hasattr(obj, "items") and not isinstance(obj, (str, bytes)):
            keys = list(obj.keys())
            display_keys = keys[:max_keys]
            suffix = "..." if len(keys) > max_keys else ""
            lines.append(f"{type(obj).__name__}(keys: [{', '.join(display_keys)}{suffix}])")
            for key in display_keys:
                value = obj[key]
                path = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    sub_keys = list(value.keys())[:max_keys]
                    sub_suffix = "..." if len(value) > max_keys else ""
                    lines.append(f"{path}: dict[{' | '.join(sub_keys)}{sub_suffix}]")
                    inner = AgentProxy._inspect_structure(value, path, depth + 1)
                    if inner:
                        lines.append(inner)
                elif isinstance(value, list):
                    if value:
                        first = value[0]
                        if isinstance(first, dict):
                            lines.append(f"{path}: list[{len(value)}] dict")
                            inner = AgentProxy._inspect_structure(first, f"{path}[0]", depth + 1)
                            if inner:
                                lines.append(inner)
                        else:
                            lines.append(f"{path}: list[{len(value)}] {type(first).__name__}")
                    else:
                        lines.append(f"{path}: list (empty)")
                elif (
                    hasattr(value, "keys")
                    and hasattr(value, "items")
                    and not isinstance(value, (str, bytes))
                ):
                    sub_keys = list(value.keys())[:max_keys]
                    sub_suffix = "..." if len(value) > max_keys else ""
                    lines.append(
                        f"{path}: {type(value).__name__}(keys: [{', '.join(sub_keys)}{sub_suffix}])"
                    )
                    inner = AgentProxy._inspect_structure(value, path, depth + 1)
                    if inner:
                        lines.append(inner)
                else:
                    preview = AgentProxy._content_preview(value)
                    lines.append(f"{path}: {type(value).__name__} = {preview}")

        else:
            lines.append(f"{type(obj).__name__}")

        return "\n".join(lines)

    def get_content_id(self, file_path: str, line_content: str) -> str:
        """Resolve a content ID for use as start_line/end_line with EditFile.

        Supports three modes:
        - **@L{number}**: e.g., `Agent.get_content_id("foo.py", "@L42")`
          returns the content ID of line 42 (1-based).
        - **content ID passthrough**: e.g., `Agent.get_content_id("foo.py", "—abcd—")`
          verifies and returns an existing content ID string.
        - **text match**: e.g., `Agent.get_content_id("foo.py", "def greet(")`
          returns the content ID of the unique line containing that text.
        """
        import os
        import re

        from cecli.helpers.hashline import resolve_content_to_hashline_ids
        from cecli.helpers.hashpos.hashpos import HASH_DELIMITER, HashPos
        from cecli.tools.utils.helpers import resolve_paths

        abs_path, rel_path = resolve_paths(self._coder, file_path)
        if not os.path.isfile(abs_path):
            raise ValueError(f"File not found: {file_path}")

        content = self._coder.io.read_text(abs_path)
        if content is None:
            raise ValueError(f"Could not read file: {file_path}")

        lines = content.splitlines()
        hp = HashPos(content)

        # @L{number} syntax
        m = re.match(r"^@L(\d+)$", line_content.strip())
        if m:
            line_num = int(m.group(1)) - 1
            if line_num < 0 or line_num >= len(lines):
                raise ValueError(f"Line {m.group(1)} out of range (file has {len(lines)} lines)")
            line_text = lines[line_num]
            occurrence = 1 + sum(1 for i in range(line_num) if lines[i] == line_text)
            return hp.get_wrapped_id(hp.generate_public_id(line_text, line_num, occurrence))

        # Content ID passthrough: already looks like a content ID
        if HashPos.FRAGMENT_RE.match(line_content):
            from cecli.helpers.hashline import ContentHashError, normalize_hashline

            try:
                normalized = normalize_hashline(line_content)
                candidates = hp.resolve_to_lines(normalized)
                if candidates:
                    return line_content
            except (ContentHashError, ValueError):
                pass

            # Fall back: value looks like a content ID (contains "—") but couldn't be
            # resolved. Strip the prefix and try to match the remaining content.
            stripped = HashPos.strip_prefix(line_content)
            if stripped != line_content and stripped.strip():
                result, _ = resolve_content_to_hashline_ids(content, stripped, None)
                if result != stripped and HASH_DELIMITER in str(result):
                    return result

            raise ValueError(f"Content ID '{line_content}' not found in {file_path}")

        # Text match via resolve_content_to_hashline_ids
        result, _ = resolve_content_to_hashline_ids(content, line_content, None)
        if result == line_content or HASH_DELIMITER not in str(result):
            # Find all matching lines for a helpful error message
            matching = [i + 1 for i, line in enumerate(lines) if line_content in line]
            if len(matching) > 1:
                line_nums = ", ".join(str(n) for n in matching[:10])
                suffix = f" ... ({len(matching)} total)" if len(matching) > 10 else ""
                raise ValueError(
                    f"Pattern '{line_content}' matches {len(matching)} locations "
                    f"in {file_path} (lines {line_nums}{suffix}). "
                    f"Use ' @L<num>' to disambiguate (e.g., '{line_content} @L{matching[0]}')."
                )
            if matching:
                raise ValueError(
                    f"Could not resolve content ID for '{line_content}' "
                    f"in {file_path} (line {matching[0]}). "
                    f"The match may not be unique enough."
                )
            raise ValueError(f"Could not resolve content ID for '{line_content}' in {file_path}")
        return result

    def resolve_regions(
        self,
        file_path: str,
        regions: list[dict[str, str]],
        exact: bool = True,
    ):
        """
        Store named region patterns for lazy content-ID resolution.

        Content IDs are resolved *on access* via `.get_start(name)` /
        `.get_end(name)`, so they are always fresh — even after
        intervening edits shift hashline positions.

        Args:
            file_path: Path to the file containing the target regions.
            regions: List of region spec dicts with "name", "start", "end" keys.
            exact: When True (default), use exact line matching (no stripping).
                   When False, use substring matching with stripped content.

        Returns an :class:`AgentRegion` instance.
        """

        from cecli.helpers.orchestration.region_resolver import AgentRegion

        return AgentRegion(file_path, self._coder, regions, exact=exact)

    async def edit_region(
        self,
        file_path: str,
        edits: list[dict[str, object]],
        change_id: str | None = None,
    ):
        """
        Thin wrapper around `EditFile` that accepts `{"start": content_id, "end": content_id}` region dicts.

        Use with `Agent.resolve_regions()` and `regions.get(name)`:

            regions = Agent.resolve_regions("foo.py", [
                {"name": "my_func", "start": "def my_func", "end": "return result"},
            ])
            await Agent.edit_region(
                file_path="foo.py",
                edits=[
                    {"region": regions.get("my_func"), "text": "def my_func():\\n    return 42"},
                ],
            )
        """

        edit_tool = self.get_tool("EditFile")

        edit_objects: list[dict[str, object]] = []
        for edit in edits:
            region = edit["region"]

            edit_objects.append(
                {
                    "file_path": file_path,
                    "operation": edit.get("operation", "replace"),
                    "start_line": region["start"],
                    "end_line": region["end"],
                    "text": edit["text"],
                }
            )

        # self._validate_edit_regions(edits, edit_objects)

        return await edit_tool.call(
            edits=edit_objects,
            change_id=change_id,
        )

    async def sleep(self, seconds: float) -> None:
        """Safe sleep - pauses execution (0-120 seconds max).

        Usage::

            await Agent.sleep(1)  # pause for 1 second
        """
        from cecli.helpers.orchestration.safe_methods import _safe_sleep

        await _safe_sleep(seconds)

    def allowed_tools(self) -> list[str]:
        """Return a sorted list of available tool names.

        Usage::

            tools = Agent.allowed_tools()
        """
        from cecli.helpers import nested

        tool_names = []
        tool_list = self._coder.get_tool_list()
        for tool in tool_list:
            name = nested.getter(tool, "function.name", "")
            if name:
                tool_names.append(name)
        return sorted(tool_names)

    def allowed_methods(self) -> list[str]:
        """Return a sorted list of all available functions and objects in the sandbox.

        Usage::

            methods = Agent.allowed_methods()
        """
        if self._env is None:
            return []
        builtins = sorted(k for k in self._env._safe_builtins.keys() if not k.startswith("_"))
        globals_list = sorted(
            k
            for k in self._env.globals.keys()
            if not k.startswith("__") and k not in ("__builtins__", "NEWLINE")
        )
        return builtins + globals_list

    @staticmethod
    def _validate_edit_regions(
        edits: list[dict[str, object]],
        edit_objects: list[dict[str, object]],
    ) -> None:
        """Reject batches where any two edit regions overlap or are adjacent.

        Adjacent edits (within 8 lines of each other) corrupt content IDs
        because the first edit regenerates IDs in the surrounding ~8-line
        window, making the second edit's target IDs stale.
        """
        _ADJACENCY_THRESHOLD = 8  # lines of ID-regeneration buffer

        if len(edits) <= 1:
            return

        # Collect (start_line, end_line, idx) for each edit
        indexed: list[tuple[int, int, int]] = []
        for i, (edit, eo) in enumerate(zip(edits, edit_objects)):
            region = edit["region"]
            sl = region.get("start_line")
            el = region.get("end_line")
            if sl is None or el is None:
                # No line numbers available — skip validation (best-effort)
                return
            indexed.append((int(sl), int(el), i))

        # Sort by start_line
        indexed.sort(key=lambda x: x[0])

        for j in range(len(indexed) - 1):
            sl_a, el_a, idx_a = indexed[j]
            sl_b, el_b, idx_b = indexed[j + 1]

            if sl_b <= el_a:
                raise ValueError(
                    f"Overlapping edit regions detected: "
                    f"edit {idx_a + 1} (lines {sl_a}-{el_a}) overlaps with "
                    f"edit {idx_b + 1} (lines {sl_b}-{el_b}). "
                    f"Split edits into separate calls."
                )
            if sl_b <= el_a + _ADJACENCY_THRESHOLD:
                raise ValueError(
                    f"Adjacent edit regions detected: "
                    f"edit {idx_a + 1} (lines {sl_a}-{el_a}) is within "
                    f"{_ADJACENCY_THRESHOLD} lines of edit {idx_b + 1} (lines {sl_b}-{el_b}). "
                    f"Content IDs within ~8 lines of an edit are regenerated, "
                    f"so adjacent edits corrupt each other's targets. "
                    f"Split edits into separate calls."
                )


# ---------------------------------------------------------------------------
# Main execution environment
# ---------------------------------------------------------------------------


class _HelpfulBuiltins(dict):
    """Custom __builtins__ dict that provides helpful hints for missing functions."""

    _HINTS: dict[str, str] = {
        "open": "Filesystem access is not available. Use the Command tool instead.",
        "eval": "eval() is disabled for security.",
        "exec": "exec() is disabled for security.",
        "__import__": "Imports are disabled. Use only the primitives provided.",
        "compile": "compile() is disabled for security.",
        "breakpoint": "breakpoint() is disabled in the sandbox.",
        "globals": "globals() is disabled. Use state or shared_state for persistence.",
        "locals": "locals() is disabled. Use state or shared_state for persistence.",
        "vars": "Use vars(obj) instead of vars() — vars(obj) returns non-dunder attrs of obj.",
        "getattr": "getattr() is disabled. Access attributes directly.",
        "setattr": "setattr() is disabled. Assign attributes directly.",
        "delattr": "delattr() is disabled. Use del obj.attr instead.",
    }

    def __missing__(self, key: str):
        hint = self._HINTS.get(key)
        if hint:
            raise NameError(f"'{key}' is not available. {hint}")
        raise NameError(f"name '{key}' is not defined")


# ---------------------------------------------------------------------------
