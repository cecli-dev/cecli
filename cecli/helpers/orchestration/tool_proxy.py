"""
Proxy for a single tool — local or MCP.

The LLM code calls ``tool.call(**params)`` and this proxy routes it
through the appropriate execution path.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class ToolResult(dict):
    """A result dict that supports both key and attribute access.

    Wraps tool call results so LLM code can use either style:

        result = await tool.call(...)
        print(result["result"])   # key access (dict-compatible)
        print(result.result)      # attribute access (convenient)
        print(result.errors)      # attribute access

    Since ToolResult is a dict subclass, all dict methods
    (``.get()``, ``.keys()``, ``in``, etc.) work as expected.
    """

    def __getattr__(self, key: str):
        if key.startswith("_"):
            raise AttributeError(f"Cannot access private attribute {key!r} on ToolResult")
        try:
            return self[key]
        except KeyError:
            raise AttributeError(
                f"ToolResult has no key {key!r}. "
                f"Available keys: {', '.join(sorted(self.keys()))}"
            ) from None

    def __setattr__(self, key: str, value) -> None:
        self[key] = value

    def __delattr__(self, key: str) -> None:
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"ToolResult has no key {key!r}") from None


class ToolProxy:
    """
    Proxy for a single tool — local or MCP.

    The LLM code calls ``tool.call(**params)`` and this proxy routes it
    through the appropriate execution path.
    """

    def __init__(
        self,
        tool_name: str,
        coder: Any,
        *,
        tool_module: Any = None,
        mcp_server: Any = None,
        mcp_tool_name: str = "",
    ) -> None:
        # Respect the per-coder tool includelist/excludelist filters
        incl = getattr(coder, "registered_tools", {}).get("included", set())
        excl = getattr(coder, "registered_tools", {}).get("excluded", set())
        name_lower = tool_name.lower()
        if incl and name_lower not in incl:
            raise ValueError(f"Tool '{tool_name}' is not in the allowed tools list.")
        if name_lower in excl:
            raise ValueError(f"Tool '{tool_name}' has been excluded.")

        self._tool_name = tool_name
        self._coder = coder
        self._tool_module = tool_module
        self._mcp_server = mcp_server
        self._mcp_tool_name = mcp_tool_name

    async def __call__(self, *args: Any, **kwargs: Any):
        """Make the proxy directly callable.

        Supports both ``await tool(key=val)`` and ``await tool("val")``.
        Positional arguments are mapped to parameter names using the
        tool's schema (when available).
        """
        if args and kwargs:
            raise TypeError(
                f"Tool '{self._tool_name}': cannot mix positional and keyword arguments"
            )

        if args:
            param_names = self._get_param_names()
            if not param_names:
                if len(args) == 1:
                    # Fallback: try common first-param names
                    for guess in (
                        "path",
                        "read",
                        "searches",
                        "edits",
                        "queries",
                        "tasks",
                        "delegations",
                        "code",
                        "command_string",
                        "command",
                        "summary",
                    ):
                        kwargs = {guess: args[0]}
                        break
                    else:
                        raise TypeError(
                            f"Tool '{self._tool_name}': cannot resolve positional "
                            f"argument – no schema available"
                        )
                else:
                    raise TypeError(
                        f"Tool '{self._tool_name}': cannot resolve positional "
                        f"arguments – no schema available"
                    )
            elif len(args) > len(param_names):
                raise TypeError(
                    f"Tool '{self._tool_name}': too many positional arguments "
                    f"({len(args)} for {len(param_names)} parameter(s): {param_names})"
                )
            else:
                kwargs = dict(zip(param_names, args))

        return await self.call(**kwargs)

    def _get_param_names(self) -> list:
        """Extract ordered parameter names from the tool's JSON Schema."""
        if self._tool_module is None:
            return []
        try:
            props = self._tool_module.SCHEMA["function"]["parameters"]["properties"]
            return list(props.keys())
        except (KeyError, TypeError, AttributeError):
            return []

    async def call(self, **kwargs: Any):
        """Execute the tool with the given keyword arguments.

        Tool results are normalized to a dict with ``result`` (list),
        ``errors`` (list), and ``details`` (list) keys, matching the
        documented orchestration contract.
        """

        if self._tool_module is not None:
            result = self._tool_module.process_response(self._coder, kwargs, _convert=False)
            if asyncio.iscoroutine(result):
                result = await result
            result = self._tool_module.ptc_format(result)
            return self._normalize_result(result)

        if self._mcp_server is not None:
            result = await self._coder._execute_mcp_tool(
                self._mcp_server, self._mcp_tool_name, kwargs
            )
            return self._normalize_result(result)

        raise ValueError(f"No executor for tool '{self._tool_name}'")

    @staticmethod
    def _normalize_result(result: Any) -> "ToolResult":
        """Normalize a tool result into a ToolResult with ``result``, ``errors``, ``details`` keys.

        Each item in the ``result`` list has the shape ``{"content": ..., "_": {...}}``.
        Supports both key access (``result["result"]``) and
        attribute access (``result.result``).
        """

        from cecli.tools.utils.responses import ToolResponse

        if isinstance(result, ToolResponse):
            data = result.to_dict()
            return ToolResult(
                {
                    "result": data.get("result", []),
                    "errors": data.get("errors", []),
                    "details": data.get("details", []),
                }
            )

        if isinstance(result, str):
            # Attempt to auto-parse a JSON-stringified ToolResponse
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    if "result" in parsed:
                        result_list = parsed["result"]
                        if not isinstance(result_list, list):
                            result_list = [result_list] if result_list else []
                        return ToolResult(
                            {
                                "result": [
                                    (
                                        item
                                        if isinstance(item, dict) and "content" in item
                                        else {"content": item, "_": {}}
                                    )
                                    for item in result_list
                                ],
                                "errors": parsed.get("errors", []),
                                "details": parsed.get("details", []),
                            }
                        )
                    return ToolResult(
                        {
                            "result": [{"content": parsed, "_": {}}],
                            "errors": [],
                            "details": [],
                        }
                    )
            except (json.JSONDecodeError, TypeError):
                pass

            # Error strings from handle_tool_error
            if result.startswith("Error in "):
                return ToolResult(
                    {
                        "result": [],
                        "errors": [result],
                        "details": [],
                    }
                )

            # Plain string result
            return ToolResult(
                {
                    "result": [{"content": result, "_": {}}],
                    "errors": [],
                    "details": [],
                }
            )

        if isinstance(result, dict):
            if "result" in result:
                result_list = result["result"]
                if not isinstance(result_list, list):
                    result_list = [result_list] if result_list else []

                out = dict(result)
                out["result"] = [
                    (
                        item
                        if isinstance(item, dict) and "content" in item
                        else {"content": item, "_": {}}
                    )
                    for item in result_list
                ]
                out.setdefault("errors", [])
                out.setdefault("details", [])
                return ToolResult(out)

            return ToolResult(
                {
                    "result": [{"content": result, "_": {}}],
                    "errors": [],
                    "details": [],
                }
            )

        # Fallback: wrap anything else
        return ToolResult(
            {
                "result": [{"content": str(result), "_": {}}] if result is not None else [],
                "errors": [],
                "details": [],
            }
        )
