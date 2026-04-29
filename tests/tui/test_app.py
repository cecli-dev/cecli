import unittest
from unittest.mock import MagicMock, patch

from textual import events

# Assuming TUI is in cecli.tui.app
from cecli.tui.app import TUI


class TestTUI(unittest.TestCase):
    @patch("cecli.tui.app.TUI.__init__", return_value=None)
    def setUp(self, mock_init):
        self.tui = TUI(coder_worker=None, output_queue=None, input_queue=None, args=None)
        # Mock attributes that might be accessed in on_mouse_move or its calls
        self.tui._mouse_hold_timer = None
        self.tui._currently_generating = False

    def test_on_mouse_move_windows(self):
        """
        Test that on_mouse_move stops the event on Windows.
        """
        # Mock the platform system to return "Windows"
        with patch("platform.system", return_value="Windows"):
            # Create a mock mouse move event
            mock_event = MagicMock(spec=events.MouseMove)

            # Call the event handler
            self.tui.on_mouse_move(mock_event)

            # Assert that event.stop() was called
            mock_event.stop.assert_called_once()

    def test_on_mouse_move_linux(self):
        """
        Test that on_mouse_move does not stop the event on Linux.
        """
        # Mock the platform system to return "Linux"
        with patch("platform.system", return_value="Linux"):
            # Create a mock mouse move event
            mock_event = MagicMock(spec=events.MouseMove)

            # Call the event handler
            self.tui.on_mouse_move(mock_event)

            # Assert that event.stop() was not called
            mock_event.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
