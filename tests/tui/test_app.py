from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual import events

# Assuming TUI is in cecli.tui.app
from cecli.tui.app import TUI


@pytest.fixture
def tui_instance(monkeypatch):
    """A pytest fixture to create a mocked TUI instance."""
    monkeypatch.setattr("cecli.tui.app.TUI.__init__", lambda *args, **kwargs: None)
    tui = TUI(coder_worker=None, output_queue=None, input_queue=None, args=None)
    tui._mouse_hold_timer = None
    tui._currently_generating = False
    tui._confirmation_lock = False
    tui._confirmations_pending = []
    tui._sub_agent_containers = {}
    return tui


def test_on_mouse_move_windows(tui_instance):
    """
    Test that on_mouse_move stops the event on Windows.
    """
    with patch("cecli.tui.app.IS_WINDOWS", True):
        mock_event = MagicMock(spec=events.MouseMove)
        tui_instance.on_mouse_move(mock_event)
        mock_event.stop.assert_called_once()


def test_on_mouse_move_linux(tui_instance):
    """
    Test that on_mouse_move does not stop the event on Linux.
    """
    with patch("cecli.tui.app.IS_WINDOWS", False):
        mock_event = MagicMock(spec=events.MouseMove)
        tui_instance.on_mouse_move(mock_event)
        mock_event.stop.assert_not_called()


def test_handle_output_message_spinner_with_agent_name(tui_instance, monkeypatch):
    """
    Test that spinner status messages display the agent name prefix
    when a sub-agent is active.
    """
    # Mock query_one to return mock widgets for all lookup types
    mock_footer = MagicMock()
    mock_footer.spinner_suffix = ""
    mock_status_bar = MagicMock()
    mock_input_area = MagicMock()
    mock_input_container = MagicMock()
    mock_output_container = MagicMock()

    def mock_query_one(selector, *args):
        # query_one may be called with class or string selector
        if isinstance(selector, type):
            name = selector.__name__
        else:
            # String selector - could be CSS like "#input, InputArea"
            if "," in selector or "#" in selector:
                return mock_input_area
            name = "MainFooter"  # Default fallback for footer lookup

        mapping = {
            "MainFooter": mock_footer,
            "StatusBar": mock_status_bar,
            "InputContainer": mock_input_container,
            "InputArea": mock_input_area,
            "OutputContainer": mock_output_container,
        }
        return mapping.get(name, mock_footer)

    tui_instance.query_one = mock_query_one

    # Mock coder worker for agent service lookups
    mock_coder = MagicMock()
    mock_coder.uuid = "primary_uuid"
    tui_instance.worker = MagicMock()
    tui_instance.worker.coder = mock_coder

    # Mock AgentService so _resolve_agent_name works
    mock_agent_service = MagicMock()
    mock_agent_info = MagicMock()
    mock_agent_info.name = "researcher"
    mock_agent_info.coder = MagicMock()
    mock_agent_info.coder.uuid = "some_uuid"
    mock_agent_service.sub_agents = {"some_uuid": mock_agent_info}
    mock_agent_service.coder = mock_coder

    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_instance",
        lambda *args: mock_agent_service,
    )

    # Test: sub-agent spinner should include agent_name="researcher"
    msg = {
        "type": "spinner",
        "action": "start",
        "text": "Thinking...",
        "coder_uuid": "some_uuid",
    }
    tui_instance.handle_output_message(msg)
    mock_footer.start_spinner.assert_called_once_with("Thinking...", agent_name="researcher")

    # Test: primary agent spinner should have agent_name="primary"
    mock_footer.reset_mock()
    msg["coder_uuid"] = "primary_uuid"
    tui_instance.handle_output_message(msg)
    mock_footer.start_spinner.assert_called_once_with("Thinking...", agent_name="primary")


def test_handle_output_message_confirmation_with_agent_name(tui_instance, monkeypatch):
    """
    Test that confirmation status messages display the agent name prefix.
    """
    mock_footer = MagicMock()
    mock_footer.spinner_suffix = ""
    mock_status_bar = MagicMock()
    mock_input_area = MagicMock()
    mock_input_container = MagicMock()
    mock_output_container = MagicMock()

    def mock_query_one(selector, *args):
        if isinstance(selector, type):
            name = selector.__name__
        else:
            if selector == "#input" or selector == "#input, InputArea":
                return mock_input_area
            elif selector == "#status-bar" or selector == "#status-bar, StatusBar":
                return mock_status_bar
            name = "MainFooter"  # Default fallback

        mapping = {
            "MainFooter": mock_footer,
            "StatusBar": mock_status_bar,
            "InputContainer": mock_input_container,
            "InputArea": mock_input_area,
            "OutputContainer": mock_output_container,
        }
        return mapping.get(name, mock_footer)

    tui_instance.query_one = mock_query_one

    # Mock coder worker for agent service lookups
    mock_coder = MagicMock()
    mock_coder.uuid = "primary_uuid"
    tui_instance.worker = MagicMock()
    tui_instance.worker.coder = mock_coder

    # Stub status_bar reference
    tui_instance.status_bar = mock_status_bar

    # Mock AgentService
    mock_agent_service = MagicMock()
    mock_agent_info = MagicMock()
    mock_agent_info.name = "researcher"
    mock_agent_info.coder = MagicMock()
    mock_agent_info.coder.uuid = "some_uuid"
    mock_agent_service.sub_agents = {"some_uuid": mock_agent_info}
    mock_agent_service.coder = mock_coder

    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_instance",
        lambda *args: mock_agent_service,
    )

    # Test: sub-agent confirmation should include agent_name="researcher"
    msg = {
        "type": "confirmation",
        "question": "Are you sure?",
        "options": {},
        "coder_uuid": "some_uuid",
    }
    tui_instance.handle_output_message(msg)
    mock_status_bar.show_confirm.assert_called_once_with(
        "Are you sure?",
        show_all=False,
        allow_tweak=False,
        allow_never=False,
        default="y",
        explicit_yes_required=False,
        agent_name="researcher",
    )


def test_handle_output_message_error_with_agent_name(tui_instance, monkeypatch):
    """
    Test that error status messages display the agent name prefix.
    """
    mock_footer = MagicMock()
    mock_footer.spinner_suffix = ""
    mock_status_bar = MagicMock()
    mock_input_area = MagicMock()
    mock_input_container = MagicMock()
    mock_output_container = MagicMock()

    def mock_query_one(selector, *args):
        if isinstance(selector, type):
            name = selector.__name__
        else:
            if selector == "#input" or selector == "#input, InputArea":
                return mock_input_area
            elif selector == "#status-bar" or selector == "#status-bar, StatusBar":
                return mock_status_bar
            name = "MainFooter"  # Default fallback

        mapping = {
            "MainFooter": mock_footer,
            "StatusBar": mock_status_bar,
            "InputContainer": mock_input_container,
            "InputArea": mock_input_area,
            "OutputContainer": mock_output_container,
        }
        return mapping.get(name, mock_footer)

    tui_instance.query_one = mock_query_one

    # Mock coder worker for agent service lookups
    mock_coder = MagicMock()
    mock_coder.uuid = "primary_uuid"
    tui_instance.worker = MagicMock()
    tui_instance.worker.coder = mock_coder

    # Mock AgentService - unknown UUID should return None (no prefix)
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_instance",
        lambda *args: MagicMock(sub_agents={}, coder=mock_coder),
    )

    # Test: error message for unknown agent should have agent_name=None
    msg = {
        "type": "error",
        "message": "Something went wrong!",
        "coder_uuid": "unknown_uuid",
    }
    tui_instance.handle_output_message(msg)
    mock_status_bar.show_notification.assert_called_once_with(
        "Something went wrong!",
        severity="error",
        timeout=5,
        agent_name=None,
    )


def test_show_error_uses_query_one(tui_instance):
    """
    Test that show_error uses query_one to get the status bar and show a notification.
    """
    mock_status_bar = MagicMock()
    tui_instance.query_one = MagicMock(return_value=mock_status_bar)

    # Import StatusBar for the assertion
    from cecli.tui.widgets import StatusBar

    tui_instance.show_error("A test error", agent_name="test_agent")

    # Assert query_one was called correctly
    tui_instance.query_one.assert_called_once_with("#status-bar", StatusBar)

    # Assert show_notification was called on the result of query_one
    mock_status_bar.show_notification.assert_called_once_with(
        "A test error",
        severity="error",
        timeout=5,
        agent_name="test_agent",
    )
    # Test: error message for unknown agent should have agent_name=None
    mock_status_bar.show_notification.reset_mock()
    msg = {
        "type": "error",
        "message": "Something went wrong!",
        "coder_uuid": "unknown_uuid",
    }
    tui_instance.handle_output_message(msg)
    mock_status_bar.show_notification.assert_called_once_with(
        "Something went wrong!",
        severity="error",
        timeout=5,
        agent_name=None,
    )


def test_handle_spawn_agent_command_dispatches_to_worker_loop(tui_instance):
    """Spawn dispatch is scheduled on the worker loop without a generate cycle."""
    worker = MagicMock()
    worker.loop = MagicMock()
    worker.coder = MagicMock()
    worker.coder.io = MagicMock()
    tui_instance.worker = worker

    input_area = MagicMock()
    tui_instance.query_one = MagicMock(return_value=input_area)
    tui_instance.add_user_message = MagicMock()

    tui_instance._handle_spawn_agent_command("/spawn-agent reviewer", "/spawn-agent reviewer")

    # Input cleared, history saved, command echoed
    assert input_area.value == ""
    input_area.save_to_history.assert_called_once_with("/spawn-agent reviewer")
    tui_instance.add_user_message.assert_called_once_with("/spawn-agent reviewer")

    # Dispatch is scheduled on the worker loop
    worker.loop.call_soon_threadsafe.assert_called_once()
    callback = worker.loop.call_soon_threadsafe.call_args[0][0]
    callback()
    worker.loop.create_task.assert_called_once()
    coro = worker.loop.create_task.call_args[0][0]

    # Running the scheduled coroutine invokes SpawnAgentCommand.execute
    import asyncio

    with patch(
        "cecli.commands.spawn_agent.SpawnAgentCommand.execute", new=AsyncMock()
    ) as mock_execute:
        asyncio.run(coro)
        mock_execute.assert_awaited_once_with(worker.coder.io, worker.coder, "reviewer")


def test_handle_spawn_agent_command_no_args_shows_usage(tui_instance):
    """Missing agent name shows usage error and does not dispatch."""
    worker = MagicMock()
    worker.loop = MagicMock()
    tui_instance.worker = worker
    tui_instance.show_error = MagicMock()
    tui_instance.query_one = MagicMock(return_value=MagicMock())

    tui_instance._handle_spawn_agent_command("/spawn-agent", "/spawn-agent")

    tui_instance.show_error.assert_called_once_with("Usage: /spawn-agent <name> [<prompt>]")
    worker.loop.call_soon_threadsafe.assert_not_called()


def test_on_input_area_submit_intercepts_spawn_agent(tui_instance):
    """'/spawn-agent' is handled directly without reaching the generate path."""
    tui_instance.query_one = MagicMock(return_value=MagicMock())
    tui_instance._handle_spawn_agent_command = MagicMock()

    message = MagicMock()
    message.value = "/spawn-agent reviewer review the code"

    tui_instance.on_input_area_submit(message)

    tui_instance._handle_spawn_agent_command.assert_called_once_with(
        "/spawn-agent reviewer review the code",
        "/spawn-agent reviewer review the code",
    )
