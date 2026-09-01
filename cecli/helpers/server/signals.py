"""Blinker signal definitions for federating TUI and WebSocket interfaces.

Each signal represents an event in the IO lifecycle. Producers (TextualInputOutput,
WebSocketSignalBridge) fire these signals via typed wrapper functions.
Consumers (TUI App, WS clients) subscribe via ``signal.connect()``.
"""

from __future__ import annotations

from typing import Any

from blinker import signal

# ── Output Signals (produced by coder/IO, consumed by TUI and WS) ──

tool_output = signal("tool-output")


def send_tool_output(
    sender: Any,
    text: str,
    msg_type: str,
    coder_uuid: str | None = None,
) -> None:
    """Fire tool_output signal."""
    tool_output.send(sender, text=text, msg_type=msg_type, coder_uuid=coder_uuid)


tool_call = signal("tool-call")


def send_tool_call(
    sender: Any,
    lines: list[str],
    coder_uuid: str | None = None,
) -> None:
    """Fire tool_call signal."""
    tool_call.send(sender, lines=lines, coder_uuid=coder_uuid)


tool_result = signal("tool-result")


def send_tool_result(
    sender: Any,
    text: str,
    coder_uuid: str | None = None,
) -> None:
    """Fire tool_result signal."""
    tool_result.send(sender, text=text, coder_uuid=coder_uuid)


stream_chunk = signal("stream-chunk")


def send_stream_chunk(
    sender: Any,
    text: str,
    coder_uuid: str | None = None,
) -> None:
    """Fire stream_chunk signal."""
    stream_chunk.send(sender, text=text, coder_uuid=coder_uuid)


start_response = signal("start-response")


def send_start_response(
    sender: Any,
    coder_uuid: str | None = None,
) -> None:
    """Fire start_response signal."""
    start_response.send(sender, coder_uuid=coder_uuid)


end_response = signal("end-response")


def send_end_response(
    sender: Any,
    coder_uuid: str | None = None,
) -> None:
    """Fire end_response signal."""
    end_response.send(sender, coder_uuid=coder_uuid)


spinner = signal("spinner")


def send_spinner(
    sender: Any,
    action: str,
    text: str,
    coder_uuid: str | None = None,
) -> None:
    """Fire spinner signal."""
    spinner.send(sender, action=action, text=text, coder_uuid=coder_uuid)


start_task = signal("start-task")


def send_start_task(
    sender: Any,
    task_id: str,
    title: str,
    task_type: str,
    coder_uuid: str | None = None,
) -> None:
    """Fire start_task signal."""
    start_task.send(
        sender,
        task_id=task_id,
        title=title,
        task_type=task_type,
        coder_uuid=coder_uuid,
    )


cost_update = signal("cost-update")


def send_cost_update(
    sender: Any,
    cost: float,
    coder_uuid: str | None = None,
) -> None:
    """Fire cost_update signal."""
    cost_update.send(sender, cost=cost, coder_uuid=coder_uuid)


error = signal("error")


def send_error(
    sender: Any,
    message: str,
    coder_uuid: str | None = None,
) -> None:
    """Fire error signal."""
    error.send(sender, message=message, coder_uuid=coder_uuid)


# ── Input Signals (produced by interfaces, consumed by coder) ──

ready_for_input = signal("ready-for-input")


def send_ready_for_input(
    sender: Any,
    files: list[str],
    commands: list[str],
    chat_files: dict[str, Any],
    coder_uuid: str | None = None,
) -> None:
    """Fire ready_for_input signal."""
    ready_for_input.send(
        sender,
        files=files,
        commands=commands,
        chat_files=chat_files,
        coder_uuid=coder_uuid,
    )


user_input = signal("user-input")


def send_user_input(
    sender: Any,
    text: str,
    coder_uuid: str | None = None,
) -> None:
    """Fire user_input signal."""
    user_input.send(sender, text=text, coder_uuid=coder_uuid)


confirmation = signal("confirmation")


def send_confirmation(
    sender: Any,
    question: str,
    response: bool,
    coder_uuid: str | None = None,
) -> None:
    """Fire confirmation signal."""
    confirmation.send(
        sender,
        question=question,
        response=response,
        coder_uuid=coder_uuid,
    )
