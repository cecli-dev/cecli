import platform
from unittest.mock import MagicMock, patch

import pytest

from cecli.dump import dump  # noqa
from cecli.linter import Linter


class TestLinter:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.linter = Linter(encoding="utf-8", root="/test/root")

    def test_init(self):
        assert self.linter.encoding == "utf-8"
        assert self.linter.root == "/test/root"
        assert "python" in self.linter.languages

    def test_set_linter(self):
        self.linter.set_linter("javascript", "eslint")
        assert self.linter.languages["javascript"] == "eslint"

    def test_get_rel_fname(self):
        import os

        assert self.linter.get_rel_fname("/test/root/file.py") == "file.py"
        expected_path = os.path.normpath("../../other/path/file.py")
        actual_path = os.path.normpath(self.linter.get_rel_fname("/other/path/file.py"))
        assert actual_path == expected_path

    @patch("subprocess.Popen")
    def test_run_cmd(self, mock_popen):
        mock_process = MagicMock()
        mock_process.returncode = 0
        # First readline returns empty string, second returns None
        mock_process.stdout.readline.side_effect = ["", None]
        # First poll returns None (process still running), second returns 0 (exit code)
        mock_process.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_process

        result = self.linter.run_cmd("test_cmd", "test_file.py", "code")
        assert result is None

    @pytest.mark.skipif(
        platform.system() != "Windows", reason="Windows-specific test for dir command"
    )
    def test_run_cmd_win(self):
        from pathlib import Path

        root = Path(__file__).parent.parent.parent.absolute().as_posix()
        linter = Linter(encoding="utf-8", root=root)
        result = linter.run_cmd("dir", "tests\\basic", "code")
        assert result is None

    @patch("subprocess.Popen")
    def test_run_cmd_with_errors(self, mock_popen):
        mock_process = MagicMock()
        mock_process.returncode = 1
        # First readline returns error, second returns empty string, third returns None
        mock_process.stdout.readline.side_effect = ["Error message", "", None]
        # First poll returns None (process still running), second returns 1 (exit code)
        mock_process.poll.side_effect = [None, 1]
        mock_popen.return_value = mock_process

        result = self.linter.run_cmd("test_cmd", "test_file.py", "code")
        assert result is not None
        assert "Error message" in result.text

    def test_run_cmd_with_special_chars(self):
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.returncode = 1
            # First readline returns error, second returns empty string, third returns None
            mock_process.stdout.readline.side_effect = ["Error message", "", None]
            # First poll returns None (process still running), second returns 1 (exit code)
            mock_process.poll.side_effect = [None, 1]
            mock_popen.return_value = mock_process

            # Test with a file path containing special characters
            special_path = "src/(main)/product/[id]/page.tsx"
            result = self.linter.run_cmd("eslint", special_path, "code")

            # Verify that the command was constructed correctly
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]

            assert special_path in call_args

            # The result should contain the error message
            assert result is not None
            assert "Error message" in result.text
