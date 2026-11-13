"""Per-step workflow hooks, independent of the native agent hooks.

A task may declare a single ``async def post_run(coder, context)`` hook, as
a callable, a ``.py`` file, inline Python, or a ``module:function`` reference.
The runner calls it after the step finishes; its return value chooses the next
queued action: ``True`` continues, ``False`` stops the run, and
``(step, prompt)`` jumps to another step with an optional replacement prompt.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import re
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .models import WorkflowConfig

logger = logging.getLogger(__name__)


@dataclass
class WorkflowRunContext:
    """State handed to a task's ``post_run`` hook.

    ``steps`` is the immutable ``{step name: original prompt}`` map from the
    workflow definition. Jumps only reorder the live queue, so looping never
    mutates or duplicates these entries.
    """

    coder: Any
    workflow: WorkflowConfig
    task: Any
    steps: Dict[str, str]
    step_name: str
    prompt: str
    status: str = "ok"
    error: Optional[str] = None
    directive: Any = None

    @property
    def available_steps(self) -> Dict[str, str]:
        """Original ``{name: prompt}`` definitions, never modified by jumps."""
        return dict(self.steps)

    def jump(self, step: str, prompt: Optional[str] = None) -> bool:
        """Queue *step* next, optionally replacing its prompt entirely."""
        self.directive = (step, prompt)
        return True

    def stop(self) -> bool:
        """Stop processing the queue after this step."""
        self.directive = False
        return False


async def run_task_hooks(coder: Any, context: WorkflowRunContext) -> Any:
    """Run the current step's ``post_run`` hook.

    Returns ``False`` to stop, a ``(step, prompt)`` tuple to jump, or
    ``None``/``True`` to continue with the queue. The first hook that redirects
    control flow wins.
    """
    spec = getattr(context.task, "post_run", None)
    if spec is None:
        return None

    result = await _execute_spec(coder, context, spec)

    if context.directive is not None:
        return context.directive

    return _normalize(result)


def _normalize(result: Any):
    """Collapse a hook result into ``False``, a ``(step, prompt)`` tuple, or None."""
    if result is False:
        return False

    if isinstance(result, (tuple, list)) and result and result[0] not in (None, True):
        step = str(result[0])
        prompt = result[1] if len(result) > 1 else None
        return (step, None if prompt is None else str(prompt))

    return None


async def _execute_spec(coder: Any, context: WorkflowRunContext, spec: Any) -> Any:
    """Execute one callable or string hook specification."""
    fn = spec if callable(spec) else _resolve_spec(str(spec), coder, context)
    if fn is None:
        logger.warning("workflow task hook not found: %r", spec)
        return None

    if isinstance(spec, str) and not inspect.iscoroutinefunction(fn):
        logger.warning("workflow task hook %r should be async", spec)

    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        parameters = {}

    try:
        result = fn(context) if len(parameters) == 1 else fn(coder, context)
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        logger.warning("workflow task hook %r failed", spec, exc_info=True)
        return None

    return result


def _resolve_spec(spec: str, coder: Any, context: WorkflowRunContext) -> Optional[Callable]:
    """Resolve a file, module reference, inline definition, or inline body."""
    text = spec.strip()
    if not text:
        return None

    workflow = getattr(context, "workflow", None)
    path = _file_hook_path(text, coder, workflow)
    if path is not None:
        module = _load_module(path)
        return getattr(module, "post_run", None) if module is not None else None

    fn = _resolve_callable(text, coder, workflow)
    if fn is not None:
        return fn

    if _looks_inline(text):
        return _resolve_inline(text)

    return None


def _resolve_callable(spec: str, coder: Any, workflow: Any = None) -> Optional[Callable]:
    """Resolve ``module:func``, ``module.func`` or ``file.py:func``."""
    import importlib

    module_part, _, attr = spec.rpartition(":")
    if not module_part:
        module_part, _, attr = spec.rpartition(".")

    if not module_part or not attr:
        return None

    if module_part.endswith(".py") or "/" in module_part or "\\" in module_part:
        path = _resolve_path(module_part, coder, workflow)
        if not path.is_file():
            return None

        module = _load_module(path)
        if module is None:
            return None
    else:
        try:
            module = importlib.import_module(module_part)
        except ImportError:
            return None

    return getattr(module, attr, None)


def _file_hook_path(text: str, coder: Any, workflow: Any) -> Optional[Path]:
    """Treat a whole ``.py`` path as a module exposing ``post_run``."""
    if not text.endswith(".py"):
        return None

    path = _resolve_path(text, coder, workflow)
    return path if path.is_file() else None


def _load_module(path: Path):
    """Load a Python hook file through the plugin module cache."""
    from cecli.helpers.plugin_manager import load_module

    try:
        return load_module(path)
    except Exception:
        logger.warning("could not load workflow task hook %s", path, exc_info=True)
        return None


def _looks_inline(text: str) -> bool:
    """Distinguish inline Python from a bare/dotted callable reference."""
    if "\n" in text or re.match(r"^(async\s+)?def\s+", text):
        return True

    if re.fullmatch(r"[A-Za-z_]\w*", text):
        return False

    if re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)+", text):
        return False

    return True


def _resolve_inline(source: str) -> Optional[Callable]:
    """Load inline Python as a temporary module exposing ``post_run``."""
    source = textwrap.dedent(source).strip()
    if re.search(r"(?m)^\s*def\s+post_run\s*\(", source):
        logger.warning("inline workflow hook should use 'async def post_run(...)'")
    if not re.search(r"(?m)^\s*(?:async\s+)?def\s+post_run\s*\(", source):
        source = "async def post_run(coder, context):\n" + textwrap.indent(source, " ")

    source = source.rstrip() + "\n"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"cecli_workflow_hook_{digest}.py"

    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        logger.warning("invalid inline workflow hook (%s): %s", exc.msg, exc.text)
        return None

    if not path.is_file() or path.read_text(encoding="utf-8") != source:
        path.write_text(source, encoding="utf-8")

    module = _load_module(path)
    return getattr(module, "post_run", None) if module is not None else None


def _resolve_path(value: str, coder: Any, workflow: Any = None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path

    root = getattr(coder, "root", None)
    candidate = Path(root).expanduser() / path if root else Path.cwd() / path
    if candidate.exists() or workflow is None:
        return candidate

    source = getattr(workflow, "source_path", None)
    if source:
        sibling = Path(source).expanduser().parent / path
        if sibling.exists():
            return sibling

    return candidate
