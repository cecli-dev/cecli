"""Translate cecli's console-oriented output into ACP v1 ``session/update`` payloads.

cecli reports progress as a stream of text: model tokens (with reasoning wrapped
in REASONING_START/REASONING_END markers), ``tool_output`` lines, and tool call
panels printed as header/body/footer. ``UpdateEmitter`` keeps just enough state
to turn that stream into the structured updates an ACP client renders:
message and thought chunks, plus ``tool_call``/``tool_call_update`` cards driven
by ``InputOutput.tool_call_event``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from cecli.helpers.responses import unprefix_tool_name
from cecli.reasoning_tags import REASONING_END, REASONING_START

# Longest tool output (in characters) mirrored into a tool call card
MAX_TOOL_TEXT = 20_000

# Wraps cecli's own console lines; longer than a typical ``` so code in them survives
CONSOLE_FENCE = "````"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Normalized cecli tool name -> ACP ToolKind
_TOOL_KINDS = {
    "readfile": "read",
    "gitstatus": "read",
    "gitlog": "read",
    "gitshow": "read",
    "gitdiff": "read",
    "gitbranch": "read",
    "gitremote": "read",
    "grep": "search",
    "explorecode": "search",
    "searchfacts": "search",
    "editfile": "edit",
    "undochange": "edit",
    "replacefacts": "edit",
    # Not "execute": Zed treats execute calls as live terminals and hides its
    # progress spinner while one runs, but cecli runs commands itself
    "command": "other",
}

# Argument keys worth showing in a tool call's title, in priority order
_TITLE_KEYS = ("command", "file_path", "path", "pattern", "query", "url", "symbol", "name")
_PATH_KEYS = ("file_path", "path")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def tool_kind(name: str) -> str:
    norm = re.sub(r"[^a-z0-9]", "", name.lower())
    if norm in _TOOL_KINDS:
        return _TOOL_KINDS[norm]
    if "fetch" in norm or "web" in norm or "scrape" in norm:
        return "fetch"
    if "search" in norm or "grep" in norm or "find" in norm:
        return "search"
    if "read" in norm or "view" in norm or norm.startswith("list"):
        return "read"
    if "delete" in norm or "remove" in norm:
        return "delete"
    if "edit" in norm or "write" in norm or "replace" in norm or "create" in norm:
        return "edit"
    return "other"


def parse_arguments(arguments: Any) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def tool_title(name: str, args: dict) -> str:
    for key in _TITLE_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            first = value.strip().splitlines()[0]
            if len(first) > 120:
                first = first[:117] + "..."
            return f"{name}: {first}"
    return name


def _fenced(text: str) -> str:
    if len(text) > MAX_TOOL_TEXT:
        text = "...(truncated)\n" + text[-MAX_TOOL_TEXT:]
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}\n{text.rstrip()}\n{fence}"


def _partial_suffix(text: str, marker: str) -> int:
    """Length of the longest suffix of ``text`` that is a proper prefix of ``marker``."""
    for size in range(min(len(text), len(marker) - 1), 0, -1):
        if marker.startswith(text[-size:]):
            return size
    return 0


def plan_entries(tasks: Any) -> list[dict]:
    """UpdateTodoList's ``tasks`` argument as ACP plan entries."""
    entries = []
    for task in tasks if isinstance(tasks, list) else []:
        if isinstance(task, dict):
            content = str(task.get("task", "")).strip()
            if task.get("done"):
                status = "completed"
            elif task.get("current"):
                status = "in_progress"
            else:
                status = "pending"
        else:
            content, status = str(task).strip(), "pending"
        if content:
            entries.append({"content": content, "priority": "medium", "status": status})
    return entries


@dataclass
class _Tool:
    id: str
    title: str
    kind: str
    status: str = "pending"
    output: list[str] = field(default_factory=list)
    synthetic: bool = False
    # Shown as an agent message once the tool runs (Yield's final answer)
    message: str | None = None


class UpdateEmitter:
    """Stateful translator from cecli output to ``session/update`` payloads.

    ``send`` receives each update dict (the value of the notification's
    ``update`` field). State is per turn; call ``finish_turn`` when it ends.
    """

    def __init__(self, send: Callable[[dict], None]):
        self._send = send
        self.root = os.getcwd()
        self._synthetic_count = 0
        self.reset()

    def reset(self) -> None:
        self._thinking = False
        self._held = ""
        self._pending_ws = ""
        self._msg_tail = ""
        self._console_open = False
        self._tools: dict[str, _Tool] = {}
        self._active: str | None = None
        self._in_panel = False

    # ── Model text ──────────────────────────────────────────────

    def stream(self, text: str, final: bool = False) -> None:
        """Model output; reasoning between the markers becomes thought chunks."""
        if text:
            self._close_console()
            self._settle_tools()

        buf = self._held + (text or "")
        self._held = ""
        while buf:
            marker = REASONING_END if self._thinking else REASONING_START
            idx = buf.find(marker)
            if idx >= 0:
                self._emit_text(buf[:idx])
                buf = buf[idx + len(marker) :]
                self._thinking = not self._thinking
                continue
            keep = 0 if final else _partial_suffix(buf, marker)
            self._emit_text(buf[: len(buf) - keep])
            self._held = buf[len(buf) - keep :]
            break

        if final:
            self._thinking = False

    def block(self, text: str) -> None:
        """A line of cecli's own output (tool_output, warnings, errors).

        Consecutive lines stream into one monospace block, so tables and
        aligned output survive markdown rendering.
        """
        if self._in_panel:
            # Tool panel body: the arguments already travel as rawInput
            return
        if not text or not text.strip():
            return
        if self._active is not None:
            self._tool_output(self._active, text)
            return

        self._flush_held()
        prefix = ""
        if not self._console_open:
            tail = self._msg_tail
            if not tail or tail.endswith("\n\n"):
                prefix = CONSOLE_FENCE + "\n"
            elif tail.endswith("\n"):
                prefix = "\n" + CONSOLE_FENCE + "\n"
            else:
                prefix = "\n\n" + CONSOLE_FENCE + "\n"
            self._console_open = True
        self._emit_message(prefix + text.strip("\n") + "\n")

    # ── Tool calls ──────────────────────────────────────────────

    def tool_event(self, tool_call_id: str, status: str, **kwargs: Any) -> None:
        if not tool_call_id:
            return
        self._close_console()
        if status == "pending":
            self._announce(tool_call_id, kwargs.get("name") or "tool", kwargs.get("arguments"))
        elif status == "in_progress":
            if self._active not in (None, tool_call_id):
                self._set_status(self._active, "completed")
            if tool_call_id not in self._tools:
                self._announce(tool_call_id, kwargs.get("name") or "tool", kwargs.get("arguments"))
            self._active = tool_call_id
            self._set_status(tool_call_id, "in_progress")
        elif status in ("completed", "failed"):
            tool = self._tools.get(tool_call_id)
            if tool is None:
                return
            result = kwargs.get("result")
            if result and not tool.output:
                # Nothing was printed while it ran; show what the model will see
                tool.output.append(str(result))
                self._update(tool, content=self._content(tool))
            if self._active == tool_call_id:
                self._active = None
            if tool.status not in ("completed", "failed"):
                self._set_status(tool_call_id, status)

    def tool_header(self, text: str) -> None:
        """Start of a printed tool panel (``type="Tool Call"``)."""
        self._in_panel = True

    def tool_footer(self) -> None:
        self._in_panel = False

    def permission_target(self, question: str, subject: str | None) -> tuple[str, bool]:
        """Pick the tool call a confirmation is about, creating one if needed.

        Returns ``(tool_call_id, synthetic)``.
        """
        if self._active is not None:
            return self._active, False

        pending = [t for t in self._tools.values() if t.status == "pending" and not t.synthetic]
        if len(pending) == 1:
            return pending[0].id, False

        self._close_console()
        self._synthetic_count += 1
        tool_id = f"cecli-confirm-{self._synthetic_count}"
        lowered = question.lower()
        if "command" in lowered or lowered.startswith("run"):
            kind = "execute"
        elif "edit" in lowered or "create" in lowered or "apply" in lowered:
            kind = "edit"
        else:
            kind = "other"

        tool = _Tool(id=tool_id, title=question.strip(), kind=kind, synthetic=True)
        if subject:
            tool.output.append(str(subject))
        elif pending:
            tool.output.append("\n".join(t.title for t in pending))
        self._tools[tool_id] = tool

        update = {
            "sessionUpdate": "tool_call",
            "toolCallId": tool_id,
            "title": tool.title,
            "kind": kind,
            "status": "pending",
        }
        if tool.output:
            update["content"] = self._content(tool)
        self._send(update)
        return tool_id, True

    def permission_prompt(self, tool_call_id: str, question: str) -> dict:
        """The ``toolCall`` of a permission request, showing the question above the options.

        A tool can be asked about more than once ("Run tools?", then "Allow
        execution of this command?"), so the question goes in the card's content
        until ``permission_resolved`` puts the tool's own content back.
        """
        tool = self._tools.get(tool_call_id)
        if tool is None or tool.synthetic:
            return {"toolCallId": tool_call_id}  # its title is already the question
        question_text = {"type": "text", "text": question.strip()}
        return {
            "toolCallId": tool_call_id,
            "content": [{"type": "content", "content": question_text}],
        }

    def permission_resolved(self, tool_call_id: str, synthetic: bool, allowed: bool) -> None:
        tool = self._tools.get(tool_call_id)
        if tool is not None and not synthetic:
            self._update(tool, content=self._content(tool) if tool.output else [])
        if allowed:
            if synthetic:
                self._set_status(tool_call_id, "completed")
            return

        # Rejected: the tool (or every tool waiting behind a group prompt) won't run
        targets = [tool_call_id]
        if synthetic:
            targets += [
                t.id for t in self._tools.values() if t.status == "pending" and not t.synthetic
            ]
        for target in targets:
            self._set_status(target, "failed")

    # ── Turn boundaries ─────────────────────────────────────────

    def finish_turn(self, cancelled: bool = False) -> None:
        self._flush_held()
        self._close_console()
        final_status = "failed" if cancelled else "completed"
        for tool in self._tools.values():
            if tool.status == "pending":
                # Announced but never started (the confirmation was skipped)
                self._set_status(tool.id, "failed")
            elif tool.status not in ("completed", "failed"):
                self._set_status(tool.id, final_status)
        self.reset()

    # ── Internals ───────────────────────────────────────────────

    def _announce(self, tool_call_id: str, name: str, arguments: Any) -> None:
        _server, short_name = unprefix_tool_name(name)
        args = parse_arguments(arguments)
        tool = _Tool(
            id=tool_call_id, title=tool_title(short_name, args), kind=tool_kind(short_name)
        )
        self._tools[tool_call_id] = tool

        norm = re.sub(r"[^a-z0-9]", "", short_name.lower())
        if norm == "updatetodolist":
            tool.title, tool.kind = "Update plan", "think"
            entries = plan_entries(args.get("tasks"))
            if entries:
                self._send({"sessionUpdate": "plan", "entries": entries})
        elif norm == "yield" and isinstance(args.get("summary"), str):
            tool.title = "Finish"
            tool.message = args["summary"]

        update = {
            "sessionUpdate": "tool_call",
            "toolCallId": tool_call_id,
            "title": tool.title,
            "kind": tool.kind,
            "status": "pending",
            "rawInput": args,
        }
        locations = self._locations(args)
        if locations:
            update["locations"] = locations
        self._send(update)

    def _locations(self, args: dict) -> list[dict]:
        for key in _PATH_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                path = value.strip()
                if not os.path.isabs(path):
                    path = os.path.join(self.root, path)
                # ACP paths are slash-separated on every platform; normpath()
                # alone would emit backslashes on Windows.
                return [{"path": os.path.normpath(path).replace(os.sep, "/")}]
        return []

    def _tool_output(self, tool_call_id: str, text: str) -> None:
        tool = self._tools.get(tool_call_id)
        if tool is None:
            return
        tool.output.append(text.rstrip("\n"))
        self._update(tool, content=self._content(tool))

    def _content(self, tool: _Tool) -> list[dict]:
        text = "\n".join(tool.output)
        return [{"type": "content", "content": {"type": "text", "text": _fenced(text)}}]

    def _set_status(self, tool_call_id: str, status: str) -> None:
        tool = self._tools.get(tool_call_id)
        if tool is None or tool.status == status:
            return
        tool.status = status
        self._update(tool, status=status)
        if status == "completed" and tool.message:
            message, tool.message = tool.message, None
            self._close_console()
            tail = self._msg_tail
            prefix = "" if not tail or tail.endswith("\n\n") else "\n\n"
            self._emit_message(prefix + message.strip() + "\n\n")

    def _update(self, tool: _Tool, **fields: Any) -> None:
        self._send({"sessionUpdate": "tool_call_update", "toolCallId": tool.id, **fields})

    def _settle_tools(self) -> None:
        """The model is talking again, so tools that already ran are done."""
        if self._active is not None:
            self._set_status(self._active, "completed")
            self._active = None
        for tool in self._tools.values():
            if tool.status == "in_progress":
                self._set_status(tool.id, "completed")

    def _close_console(self) -> None:
        if self._console_open:
            self._console_open = False
            self._emit_message(CONSOLE_FENCE + "\n\n")

    def _flush_held(self) -> None:
        if self._held:
            held, self._held = self._held, ""
            self._emit_text(held)

    def _emit_text(self, text: str) -> None:
        if not text:
            return
        if self._thinking:
            # Whitespace before a thought (e.g. the newline ahead of a reasoning
            # marker) would otherwise surface as an empty message
            self._pending_ws = ""
            self._send(
                {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": text}}
            )
        elif not text.strip():
            self._pending_ws += text
        else:
            self._emit_message(text)

    def _emit_message(self, text: str) -> None:
        text, self._pending_ws = self._pending_ws + text, ""
        self._msg_tail = (self._msg_tail + text)[-2:]
        self._send(
            {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}
        )
