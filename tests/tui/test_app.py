import pytest
from unittest.mock import MagicMock, patch

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
    return tui


def test_on_mouse_move_windows(tui_instance):
    """
    Test that on_mouse_move stops the event on Windows.
    """
    with patch("platform.system", return_value="Windows"):
        mock_event = MagicMock(spec=events.MouseMove)
        tui_instance.on_mouse_move(mock_event)
        mock_event.stop.assert_called_once()


def test_on_mouse_move_linux(tui_instance):
    """
    Test that on_mouse_move does not stop the event on Linux.
    """
    with patch("platform.system", return_value="Linux"):
        mock_event = MagicMock(spec=events.MouseMove)
        tui_instance.on_mouse_move(mock_event)
        mock_event.stop.assert_not_called()
