"""
Sandboxed execution environment for LLM-generated orchestration code.

Provides AgentExecutionEnv, ToolProxy, AgentProxy, and the context block builder.
"""

from __future__ import annotations

import ast
import asyncio
import collections
import datetime
import itertools
import json
import logging
import math
import re
import traceback
from typing import Any

from cecli.helpers import nested, responses
from cecli.helpers.orchestration.agent_proxy import AgentProxy
from cecli.helpers.orchestration.safe_methods import (
    GatherResult,
    _escape_newlines_in_strings,
    _HelpfulBuiltins,
    _safe_dir,
    _safe_gather,
    _safe_getattr,
    _safe_hasattr,
    _safe_sleep,
    _safe_typeof,
    _safe_vars,
    _SafeJson,
    _SafeModuleProxy,
    _SafePathlib,
    _SafeRe,
    _SafeTraceback,
    _strip_allowed_imports,
)
from cecli.helpers.orchestration.security import (
    LoopYieldInjector,
    SecurityError,
    SecurityFilter,
    _cooperative_yield,
    _security_raise,
)
from cecli.helpers.orchestration.tool_proxy import ToolProxy

logger = logging.getLogger(__name__)


class TrackedDict(dict):
    """A dict subclass that records mutations (set/delete/clear/pop) on a parent env.

    Tracks both adds (new keys) and modifications (existing key value changes)
    so the environment can report only changed variables after execution.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner: AgentExecutionEnv | None = None
        self._is_shared: bool = False

    def _set_owner(self, owner: AgentExecutionEnv, is_shared: bool = False) -> None:
        self._owner = owner
        self._is_shared = is_shared

    def __getattr__(self, key: str):
        """Route attribute reads through dict lookup.

        Internal attrs (_owner, _is_shared) are accessed via object.__getattribute__
        to avoid recursion. All other names are looked up in the dict.
        """
        if key.startswith("_"):
            raise AttributeError(f"Cannot access private attribute {key!r} on TrackedDict")
        try:
            return self[key]
        except KeyError:
            raise AttributeError(
                f"TrackedDict has no key {key!r}. "
                f"Available keys: {', '.join(sorted(self.keys()))}"
            ) from None

    def __setattr__(self, key: str, value) -> None:
        """Route attribute writes through dict __setitem__.

        Internal attrs (_owner, _is_shared) are set directly on the instance
        to avoid polluting dict state.
        """
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self[key] = value

    def __delattr__(self, key: str) -> None:
        """Route attribute deletes through dict __delitem__."""
        if key.startswith("_"):
            object.__delattr__(self, key)
        else:
            del self[key]

    def __setitem__(self, key, value):
        is_new = key not in self
        super().__setitem__(key, value)
        if self._owner is not None:
            self._owner._record_mutation(key, is_shared=self._is_shared, is_new=is_new)

    def __delitem__(self, key):
        if self._owner is not None:
            self._owner._record_mutation(key, is_shared=self._is_shared)
        super().__delitem__(key)

    def clear(self):
        if self._owner is not None:
            for key in list(self):
                self._owner._record_mutation(key, is_shared=self._is_shared)
            super().clear()
        else:
            super().clear()

    def pop(self, key, *args):
        if key in self:
            if self._owner is not None:
                self._owner._record_mutation(key, is_shared=self._is_shared)
            return super().pop(key, *args)
        if args:
            return args[0]
        raise KeyError(key)

    def popitem(self):
        if not self:
            raise KeyError("popitem(): dictionary is empty")
        key = next(iter(self))
        if self._owner is not None:
            self._owner._record_mutation(key, is_shared=self._is_shared)
        return super().popitem()

    def get(self, key, default=None):
        """Return value for *key*, falling through to ``shared_state`` if not found locally.

        When called on a local state dict (i.e., ``state``, not ``shared_state``
        itself), keys not present locally are looked up in the shared state
        before returning *default*.  This makes it easy to read globally-set
        values without an explicit fallback::

            val = state.get("my_global")  # checks local, then shared_state
        """
        if key in self:
            return self[key]
        # Don't fall through when this IS the shared_state (avoid infinite loop)
        if self._is_shared:
            return default
        if self._owner is not None:
            shared = type(self._owner)._shared_state
            if key in shared:
                return shared[key]
        return default


# ---------------------------------------------------------------------------
# Safe primitives exposed to the sandbox


def _make_sandbox_dir(globals_dict, locals_dict):
    """Create a safe dir() callable that handles both no-arg and obj modes.

    When called without arguments (like the builtin ``dir()``), returns a sorted
    list of public (non-dunder) names from the sandbox globals, locals, and
    builtins (including pre-imported modules like ``re``, ``math``, etc.).
    When called with an object, delegates to ``_safe_dir(obj)``.
    """
    _SENTINEL = object()

    def sandbox_dir(obj=_SENTINEL):
        if obj is _SENTINEL:
            names = set(globals_dict.keys()) | set(locals_dict.keys())
            builtins = globals_dict.get("__builtins__", {})
            if isinstance(builtins, dict):
                names |= set(builtins.keys())
            return sorted(n for n in names if not n.startswith("_"))

        return _safe_dir(obj)

    return sandbox_dir


class AgentExecutionEnv:
    """
    Sandboxed REPL environment for executing LLM-generated orchestration code.

    Provides:
    - `Agent`  : proxy to look up and call tools and other core agentic utility methods
    - `gather` : safe parallel execution helper
    - `state`  : persistent dict (survives across Orchestrate calls)
    - `print`  : captured output
    - `range`, `len`, `int`, `str`, `list`, `dict`, `bool`, `Exception`

    Security guarantees:
    - AST security filtering before compilation
    - Loop yield injection
    - Timeout via asyncio.wait_for
    - No imports, no private attributes, no dangerous builtins
    """

    # Shared across all AgentExecutionEnv instances — any agent can read/write
    _shared_state: TrackedDict = TrackedDict()

    def __init__(self, coder: Any, orchestration_config: dict[str, Any] | None = None) -> None:
        from typing import Any as _Any

        self._orchestration_config: dict[str, _Any] = orchestration_config or {}
        self._DANGEROUS_BUILTINS: set[str] = {
            "eval",
            "exec",
            "open",
            "__import__",
            "compile",
            "breakpoint",
            "globals",
            "locals",
        }

        self.state = TrackedDict()
        self.state._set_owner(self)
        self._shared_state._set_owner(self, is_shared=True)

        # Initialize early so _safe_builtins can reference them
        self.globals: dict[str, _Any] = {}
        self.locals: dict[str, _Any] = {}

        _disable_sec = self._orchestration_config.get("disable_security", False)

        self._safe_builtins: dict[str, _Any] = {
            "print": print,
            "range": range,
            "len": len,
            "int": int,
            "str": str,
            "float": float,
            "list": list,
            "dict": dict,
            "bool": bool,
            "tuple": tuple,
            "set": set,
            "typeof": _safe_typeof,
            "type": _safe_typeof,
            "vars": _safe_vars,
            "dir": _make_sandbox_dir(self.globals, self.locals),
            "isinstance": isinstance,
            "hasattr": _safe_hasattr,
            "getattr": _safe_getattr,
            "repr": repr,
            "enumerate": enumerate,
            "zip": zip,
            "sorted": sorted,
            "reversed": reversed,
            "min": min,
            "max": max,
            "sum": sum,
            "abs": abs,
            "round": round,
            "any": any,
            "all": all,
            "filter": filter,
            "map": map,
            "chr": chr,
            "next": next,
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "AttributeError": AttributeError,
            "RuntimeError": RuntimeError,
            "NameError": NameError,
            "ZeroDivisionError": ZeroDivisionError,
            "StopIteration": StopIteration,
            "ArithmeticError": ArithmeticError,
            "LookupError": LookupError,
            "re": _SafeRe,
            "math": _SafeModuleProxy(math, disable_security=_disable_sec),
            "itertools": _SafeModuleProxy(itertools, disable_security=_disable_sec),
            "collections": _SafeModuleProxy(collections, disable_security=_disable_sec),
            "datetime": _SafeModuleProxy(datetime, disable_security=_disable_sec),
            "traceback": _SafeTraceback,
            "pathlib": _SafePathlib,
        }

        # Task 3: allowed_builtins — extend _safe_builtins with user-requested builtins
        allowed_builtins: list[str] = self._orchestration_config.get("allowed_builtins", [])
        for name in allowed_builtins:
            if name.startswith("_"):
                raise ValueError(f"Cannot allow private builtin '{name}'")
            if name in self._DANGEROUS_BUILTINS and not self._orchestration_config.get(
                "disable_security"
            ):
                raise ValueError(f"Cannot allow dangerous builtin '{name}'")
            self._safe_builtins[name] = __builtins__[name]

        # When security is fully disabled, expose dangerous builtins
        if self._orchestration_config.get("disable_security", False):
            for name in self._DANGEROUS_BUILTINS:
                self._safe_builtins[name] = __builtins__[name]
            # Restore real getattr/hasattr when security is disabled
            self._safe_builtins["getattr"] = getattr
            self._safe_builtins["hasattr"] = hasattr

        # When allow_classes is enabled, expose __build_class__ needed by Python
        if self._orchestration_config.get("allow_classes", False):
            self._safe_builtins["__build_class__"] = __builtins__["__build_class__"]

        # When allowed_imports is configured, expose __import__ so imports work,
        # and add __name__ since imported modules reference it.
        if self._orchestration_config.get("allowed_imports"):
            self._safe_builtins["__import__"] = __builtins__["__import__"]
            self._safe_builtins["__name__"] = "__sandbox__"

        self.globals.clear()
        _agent = AgentProxy(coder)
        _agent._env = self

        self.globals.update(
            {
                "__builtins__": _HelpfulBuiltins(self._safe_builtins),
                "Agent": _agent,
                "gather": _safe_gather,
                "json": _SafeJson,
                "state": self.state,
                "shared_state": AgentExecutionEnv._shared_state,
                "__yield": _cooperative_yield,
                "__security_raise": _security_raise,
                "NEWLINE": "\n",
            }
        )
        self.locals.clear()

        def _make_reset(env_locals, env_state):
            def reset_func(local_vars: bool = True, state: bool = False) -> None:
                """Clear execution namespaces.

                Args:
                    local_vars: Clear the ephemeral locals namespace (default True).
                    state: Also clear per-agent state keys (default False).
                           Shared state is never affected.
                """
                if local_vars:
                    env_locals.clear()
                if state:
                    env_state.clear()

            return reset_func

        self.globals["reset"] = _make_reset(self.locals, self.state)

    @staticmethod
    def _size_of(value: Any) -> int:
        """Return a meaningful size metric for a state variable."""
        if value is None:
            return 0
        if isinstance(value, (str, list, tuple, set, dict)):
            return len(value)
        return len(str(value))

    @staticmethod
    def _value_preview(value: Any) -> str:
        """Return a short preview of a value for state snapshot display."""
        if value is None:
            return "None"
        s = str(value)
        if len(s) > 80:
            return s[:77] + "..."
        return s

    def _record_mutation(self, key: object, is_shared: bool = False, is_new: bool = False) -> None:
        """Record that a state key was modified during this execution.

        Called automatically by TrackedDict on set/delete/clear/pop.
        """
        if not hasattr(self, "_modified_keys"):
            self._modified_keys: set = set()
        if not hasattr(self, "_modified_shared_keys"):
            self._modified_shared_keys: set = set()
        if is_shared:
            self._modified_shared_keys.add(key)
        else:
            self._modified_keys.add(key)

    def _state_snapshot(self) -> list:
        """Build a list of state variable descriptors.

        For local state, only modified keys are reported (with `modified: True`).
        For shared state, all keys are reported so that cross-agent writes are
        visible even when the current agent didn't modify them. Keys modified
        by the current execution are marked `modified: True`; all others are
        `modified: False`.
        """
        modified_keys = getattr(self, "_modified_keys", set())
        modified_shared_keys = getattr(self, "_modified_shared_keys", set())
        entries = []

        for key, value in self.state.items():
            if key not in modified_keys:
                continue
            entries.append(
                {
                    "name": key,
                    "type": type(value).__name__,
                    "size": self._size_of(value),
                    "modified": True,
                    "scope": "local",
                    "preview": self._value_preview(value),
                }
            )

        for key, value in self._shared_state.items():
            entries.append(
                {
                    "name": key,
                    "type": type(value).__name__,
                    "size": self._size_of(value),
                    "modified": key in modified_shared_keys,
                    "scope": "shared",
                    "preview": self._value_preview(value),
                }
            )

        return entries

    async def execute(self, code_str: str, values: dict | None = None) -> dict:

        code_str = code_str.strip()
        code_str = _escape_newlines_in_strings(code_str)
        extra_allowed = frozenset(self._orchestration_config.get("allowed_imports", []))
        code_str, extra_globals = _strip_allowed_imports(code_str, extra_allowed=extra_allowed)
        self.globals.update(extra_globals)
        if not code_str:
            return {"results": "", "state_variables": self._state_snapshot()}

        injected_keys = []

        if values:
            for key, value in values.items():
                var_name = f"_o_{key}"
                self.globals[var_name] = value
                injected_keys.append(var_name)

        captured_output: list[str] = []

        # Clear mutation tracking for this execution
        self._modified_keys = set()
        self._modified_shared_keys = set()

        def _capture_print(*args: Any, **kwargs: Any) -> None:
            sep = kwargs.pop("sep", " ")
            end = kwargs.pop("end", "\n")
            kwargs.pop("file", None)  # silently ignore
            kwargs.pop("flush", None)  # silently ignore
            if kwargs:
                raise TypeError(f"print() got unexpected keyword arguments: {list(kwargs.keys())}")
            captured_output.append(sep.join(str(a) for a in args) + end)

        self.globals["__builtins__"]["print"] = _capture_print

        try:
            tree = ast.parse(code_str, filename="<agent_env>", mode="exec")
        except SyntaxError as e:
            code = f"Syntax Error in orchestration code: {e}"
            return {"results": code, "state_variables": self._state_snapshot()}

        def _build_result(msg: str = "") -> dict:
            print_output = "".join(captured_output)
            parts = []
            if print_output:
                parts.append(print_output.rstrip("\n"))
            if msg:
                parts.append(msg)
            code = "\n".join(parts) if parts else ""
            return {"results": code, "state_variables": self._state_snapshot()}

        try:
            if not self._orchestration_config.get("disable_security", False):
                tree = SecurityFilter(
                    allowed_imports=extra_allowed,
                    allow_classes=self._orchestration_config.get("allow_classes", False),
                ).visit(tree)
            if not self._orchestration_config.get("disable_loop_protection", False):
                tree = LoopYieldInjector().visit(tree)
            ast.fix_missing_locations(tree)
        except SecurityError as e:
            return _build_result(f"Security Error: {e}")
        except Exception as e:
            return _build_result(f"AST Transform Error: {e}")

        wrapper_func = ast.AsyncFunctionDef(
            name="__agent_async_runner",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=tree.body,
            decorator_list=[],
        )

        ast.fix_missing_locations(wrapper_func)
        mod = ast.Module(body=[wrapper_func], type_ignores=[])

        try:
            compiled_code = compile(mod, filename="<agent_env>", mode="exec")
        except Exception as e:
            code = f"Compilation Error: {e}"
            return {"results": code, "state_variables": self._state_snapshot()}

        try:
            exec(compiled_code, self.globals, self.locals)
            runner_coro = self.locals["__agent_async_runner"]()
            result = await runner_coro
        except asyncio.CancelledError:
            return _build_result("Execution Error: Script was cancelled.")
        except SecurityError as e:
            return _build_result(f"Security Error: {e}")
        except Exception as e:
            tb = traceback.format_exc()
            logger.warning("Orchestration execution error: %s\n%s", e, tb)
            return _build_result(f"Execution Error: {type(e).__name__}: {e}")
        finally:
            self.locals.pop("__agent_async_runner", None)
            self.globals["__builtins__"]["print"] = print
            for key in injected_keys:
                self.globals.pop(key, None)
            # Mutation tracking is handled automatically by TrackedDict

        return _build_result()


# flake8: noqa
# fmt: off

def build_orchestration_context_block(agent_config: dict[str, Any]) -> str | None:
    """
    Build the orchestration context block that explains calling conventions.

    Only returns content if `allow_orchestration` is enabled in agent_config.
    """
    if not agent_config.get("allow_orchestration", True):
        return None

    orchestration_config = agent_config.get("orchestration", {})

    context = """<context name="orchestration" from="agent">
The `Orchestrate` tool runs Python in a sandbox where you can script other tools programmatically. 
Use it for batch, loop-heavy, and repeat-able workflows.
Variables and helpers persist across calls; `state` persists across all Orchestrate calls in the session.
You may need to explore the below primitives to understand how to use the sandbox effectively.

### Primitives

| Primitive | What it does |
|-----------|--------------|
| `Agent.allowed_methods()` / `Agent.allowed_tools()` | List helper methods and available tools |
| `Agent.get_tool(name)` | Get a tool proxy (case-insensitive; `Local--` / `{{Server Name}}--` prefixes ok) |
| `await tool.call(**params)` | Run a tool; returns `{"result": [...], "errors": [...], "details": [...]}`, items with shape `{"content", "_"}` |
| `Agent.peek(result)` / `Agent.get_value(result, path, default?)` | Inspect / extract values from tool results. path is dot-separated string |
| `Agent.resolve_regions(path, specs)` / `Agent.edit_region(path, edits)` | Resolve text boundaries once, then apply edits |
| `gather(**tasks)` | Run tasks concurrently; results expose `.key` and `["key"]` |
| `state` / `shared_state` | Persistent dicts; `state.get(k)` falls back to `shared_state` |
| `print(...)` / `reset(local_vars=True, state=False)` | Emit output / clear namespaces |
| `typeof(x)`, `isinstance(x, t)`, `hasattr(x, n)`, `repr(x)`, `vars(obj)` | Type inspection and debugging |

### Region editing

- `resolve_regions(path, specs)`: 
  `specs` = `[{"name", "start", "end", "start_line_hint"?, "end_line_hint"?}]`; `start`/`end` are line text, `@L{num}`, or a content ID. 
  Returns `regions` with `.get(name)` -> `{"start", "end", "start_line", "end_line"}` plus `.get_start(name)` / `.get_end(name)`.
- `edit_region(path, edits)`: 
  `edits` = `[{"region": regions.get(name), "text", "operation" ("replace"|"delete", default "replace")}]`.

### Modules

Pre-imported, read-only: `re`, `math`, `itertools`, `collections`, `datetime`, `pathlib` (I/O blocked), `json`, `traceback`. Any other import fails.

### Conventions

- Keyword args only; `gather()` takes named tasks
- Do not touch private (`_`) attributes or `__builtins__`
- Always `await` tool calls
- Inspect tool results with `Agent.peek()` / `Agent.get_value()`; edit files via `Agent.resolve_regions()` + `Agent.edit_region()` or `EditFile` directly
</context>"""

    # Task 6: Append sandbox configuration overrides when non-empty
    if orchestration_config:
        overrides: list[str] = []
        if orchestration_config.get("allowed_imports"):
            overrides.append(
                f"- Allowed extra imports: {orchestration_config['allowed_imports']}"
            )
        if orchestration_config.get("allowed_builtins"):
            overrides.append(
                f"- Allowed extra builtins: {orchestration_config['allowed_builtins']}"
            )
        if orchestration_config.get("allow_classes"):
            overrides.append("- Class definitions are allowed (__init__, __str__, etc.)")
        if orchestration_config.get("disable_security"):
            overrides.append("- ⚠ Security filtering is DISABLED")
        if orchestration_config.get("disable_loop_protection"):
            overrides.append("- ⚠ Loop protection is DISABLED")
        if overrides:
            context += "\n### Sandbox Configuration Overrides\n" + "\n".join(overrides) + "\n"

    return context


# flake8: noqa
# fmt: on
