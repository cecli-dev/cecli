import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from cecli.coders import Coder
from cecli.dump import dump  # noqa: F401
from cecli.io import AutoCompleter, ConfirmGroup, InputOutput
from cecli.utils import ChdirTemporaryDirectory


class TestInputOutput:
    @pytest.mark.parametrize(
        "ending,expected_newline",
        [
            ("platform", None),
            ("lf", "\n"),
            ("crlf", "\r\n"),
            ("preserve", None),
        ],
    )
    def test_valid_line_endings(self, ending, expected_newline):
        """Test that valid line ending options are correctly processed."""
        io = InputOutput(line_endings=ending)
        assert io.newline == expected_newline

    def test_invalid_line_endings(self):
        """Test that invalid line ending values raise appropriate error."""
        with pytest.raises(ValueError) as cm:
            InputOutput(line_endings="invalid")
        assert "Invalid line_endings value: invalid" in str(cm.value)
        # Check each valid option is in the error message
        assert "platform" in str(cm.value)
        assert "crlf" in str(cm.value)
        assert "lf" in str(cm.value)
        assert "preserve" in str(cm.value)

    def test_no_color_environment_variable(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            io = InputOutput(fancy_input=False)
            assert not io.pretty

    def test_color_initialization(self):
        """Test that color values are properly initialized with # prefix"""
        # Test with hex colors without #
        io = InputOutput(
            user_input_color="00cc00",
            tool_error_color="FF2222",
            tool_warning_color="FFA500",
            assistant_output_color="0088ff",
            pretty=True,
        )

        # Check that # was added to hex colors
        assert io.user_input_color == "#00cc00"
        assert io.tool_error_color == "#FF2222"
        assert io.tool_warning_color == "#FFA500"
        assert io.assistant_output_color == "#0088ff"

        # Test with named colors (should be unchanged)
        io = InputOutput(user_input_color="blue", tool_error_color="red", pretty=True)

        assert io.user_input_color == "blue"
        assert io.tool_error_color == "red"

        # Test with pretty=False (should not modify colors)
        io = InputOutput(user_input_color="00cc00", tool_error_color="FF2222", pretty=False)

        assert io.user_input_color is None
        assert io.tool_error_color is None

    def test_dumb_terminal(self):
        with patch.dict(os.environ, {"TERM": "dumb"}):
            io = InputOutput(fancy_input=True)
            assert io.is_dumb_terminal
            assert not io.pretty
            assert io.prompt_session is None

    def test_autocompleter_get_command_completions(self):
        # Step 3: Mock the commands object
        commands = MagicMock()
        commands.get_commands.return_value = ["/help", "/add", "/drop"]
        commands.matching_commands.side_effect = lambda inp: (
            [cmd for cmd in commands.get_commands() if cmd.startswith(inp.strip().split()[0])],
            inp.strip().split()[0],
            " ".join(inp.strip().split()[1:]),
        )
        commands.get_raw_completions.return_value = None
        commands.get_completions.side_effect = lambda cmd: (
            ["file1.txt", "file2.txt"] if cmd == "/add" else None
        )

        # Step 4: Create an instance of AutoCompleter
        root = ""
        rel_fnames = []
        addable_rel_fnames = []
        autocompleter = AutoCompleter(
            root=root,
            rel_fnames=rel_fnames,
            addable_rel_fnames=addable_rel_fnames,
            commands=commands,
            encoding="utf-8",
        )

        # Step 5: Set up test cases
        test_cases = [
            # Input text, Expected completion texts
            ("/", ["/help", "/add", "/drop"]),
            ("/a", ["/add"]),
            ("/add f", ["file1.txt", "file2.txt"]),
        ]

        # Step 6: Iterate through test cases
        for text, expected_completions in test_cases:
            document = Document(text=text)
            complete_event = CompleteEvent()
            words = text.strip().split()

            # Call get_command_completions
            completions = list(
                autocompleter.get_command_completions(
                    document,
                    complete_event,
                    text,
                    words,
                )
            )

            # Extract completion texts
            completion_texts = [comp.text for comp in completions]

            # Assert that the completions match expected results
            assert set(completion_texts) == set(expected_completions)

    def test_autocompleter_with_non_existent_file(self):
        root = ""
        rel_fnames = ["non_existent_file.txt"]
        addable_rel_fnames = []
        commands = None
        autocompleter = AutoCompleter(root, rel_fnames, addable_rel_fnames, commands, "utf-8")
        assert autocompleter.words == set(rel_fnames)

    def test_autocompleter_with_unicode_file(self):
        with ChdirTemporaryDirectory():
            root = ""
            fname = "file.py"
            rel_fnames = [fname]
            addable_rel_fnames = []
            commands = None
            autocompleter = AutoCompleter(root, rel_fnames, addable_rel_fnames, commands, "utf-8")
            assert autocompleter.words == set(rel_fnames)

            Path(fname).write_text("def hello(): pass\n")
            autocompleter = AutoCompleter(root, rel_fnames, addable_rel_fnames, commands, "utf-8")
            autocompleter.tokenize()
            dump(autocompleter.words)
            assert autocompleter.words == set(rel_fnames + [("hello", "`hello`")])

            encoding = "utf-16"
            some_content_which_will_error_if_read_with_encoding_utf8 = "ÅÍÎÏ".encode(encoding)
            with open(fname, "wb") as f:
                f.write(some_content_which_will_error_if_read_with_encoding_utf8)

            autocompleter = AutoCompleter(root, rel_fnames, addable_rel_fnames, commands, "utf-8")
            assert autocompleter.words == set(rel_fnames)

    @patch("builtins.input", return_value="test input")
    def test_get_input_is_a_directory_error(self, mock_input):
        io = InputOutput(pretty=False, fancy_input=False)  # Windows tests throw UnicodeDecodeError
        root = "/"
        rel_fnames = ["existing_file.txt"]
        addable_rel_fnames = ["new_file.txt"]
        commands = MagicMock()

        # Simulate IsADirectoryError
        with patch("cecli.io.open", side_effect=IsADirectoryError):
            result = asyncio.run(io.get_input(root, rel_fnames, addable_rel_fnames, commands))
            assert result == "test input"
            mock_input.assert_called_once()

    @patch("builtins.input")
    def test_confirm_ask_explicit_yes_required_with_yes_true(self, mock_input):
        """Test explicit_yes_required=True overrides self.yes=True and prompts user"""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        mock_input.return_value = "n"
        result = asyncio.run(io.confirm_ask("Are you sure?", explicit_yes_required=True))
        assert not result
        mock_input.assert_called()

    @patch("builtins.input")
    def test_confirm_ask_explicit_yes_required_with_yes_false(self, mock_input):
        """Test explicit_yes_required=True with self.yes=False prompts user"""
        io = InputOutput(pretty=False, fancy_input=False, yes=False)
        mock_input.return_value = "n"
        result = asyncio.run(io.confirm_ask("Are you sure?", explicit_yes_required=True))
        assert not result
        mock_input.assert_called()

    @patch("builtins.input")
    def test_confirm_ask_explicit_yes_required_user_input(self, mock_input):
        """Test explicit_yes_required=True requires user input when yes=None"""
        io = InputOutput(pretty=False, fancy_input=False)
        mock_input.return_value = "y"
        result = asyncio.run(io.confirm_ask("Are you sure?", explicit_yes_required=True))
        assert result is not None
        mock_input.assert_called()

    @patch("builtins.input")
    def test_confirm_ask_without_explicit_yes_uses_yes_flag(self, mock_input):
        """Test explicit_yes_required=False allows self.yes=True to skip prompting"""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        mock_input.return_value = "y"
        result = asyncio.run(io.confirm_ask("Are you sure?", explicit_yes_required=False))
        assert result is not None
        mock_input.assert_not_called()

    @patch("builtins.input")
    def test_confirm_ask_group_user_selects_all(self, mock_input):
        """Test group with no preference when user selects 'All'"""
        io = InputOutput(pretty=False, fancy_input=False)
        group = ConfirmGroup()
        mock_input.return_value = "a"
        result = asyncio.run(io.confirm_ask("Are you sure?", group=group))
        assert result is not None
        assert group.preference == "all"
        mock_input.assert_called_once()

    @patch("builtins.input")
    def test_confirm_ask_group_preference_all_skips_prompt(self, mock_input):
        """Test group with 'all' preference does not prompt user"""
        io = InputOutput(pretty=False, fancy_input=False)
        group = ConfirmGroup()
        group.preference = "all"
        result = asyncio.run(io.confirm_ask("Are you sure?", group=group))
        assert result is not None
        mock_input.assert_not_called()

    @patch("builtins.input")
    def test_confirm_ask_group_user_selects_skip_all(self, mock_input):
        """Test group with no preference when user selects 'Skip all'"""
        io = InputOutput(pretty=False, fancy_input=False)
        group = ConfirmGroup()
        mock_input.return_value = "s"
        result = asyncio.run(io.confirm_ask("Are you sure?", group=group))
        assert not result
        assert group.preference == "skip"
        mock_input.assert_called_once()

    @patch("builtins.input")
    def test_confirm_ask_group_preference_skip_skips_prompt(self, mock_input):
        """Test group with 'skip' preference does not prompt user"""
        io = InputOutput(pretty=False, fancy_input=False)
        group = ConfirmGroup()
        group.preference = "skip"
        result = asyncio.run(io.confirm_ask("Are you sure?", group=group))
        assert not result
        mock_input.assert_not_called()

    @patch("builtins.input")
    def test_confirm_ask_group_with_explicit_yes_no_all_option(self, mock_input):
        """Test group with explicit_yes_required does not offer 'All' option"""
        io = InputOutput(pretty=False, fancy_input=False)
        group = ConfirmGroup()
        mock_input.return_value = "y"
        result = asyncio.run(
            io.confirm_ask("Are you sure?", group=group, explicit_yes_required=True)
        )
        assert result is not None
        assert group.preference is None
        mock_input.assert_called_once()
        assert "(A)ll" not in mock_input.call_args[0][0]

    @pytest.mark.parametrize(
        "input_value,expected_result,description",
        [
            ("y", True, "User selects 'Yes'"),
            ("n", False, "User selects 'No'"),
            ("", True, "Empty input defaults to Yes"),
            ("s", False, "'skip' functions as 'no' without group"),
            ("a", True, "'all' functions as 'yes' without group"),
            ("skip", False, "Full word 'skip' functions as 'no' without group"),
            ("all", True, "Full word 'all' functions as 'yes' without group"),
        ],
    )
    @patch("builtins.input")
    def test_confirm_ask_yes_no_responses(
        self, mock_input, input_value, expected_result, description
    ):
        """Test various user responses to confirm_ask without group"""
        io = InputOutput(pretty=False, fancy_input=False)
        mock_input.return_value = input_value
        result = asyncio.run(io.confirm_ask("Are you sure?"))
        if expected_result:
            assert result is not None, f"Failed: {description}"
        else:
            assert not result, f"Failed: {description}"
        mock_input.assert_called_once()

    @patch("builtins.input", side_effect=["d"])
    def test_confirm_ask_allow_never_first_call(self, mock_input):
        """Test 'don't ask again' functionality adds to never_prompts"""
        io = InputOutput(pretty=False, fancy_input=False)
        result = asyncio.run(io.confirm_ask("Are you sure?", allow_never=True))
        assert not result
        mock_input.assert_called_once()
        assert ("Are you sure?", None) in io.never_prompts

    @patch("builtins.input")
    def test_confirm_ask_allow_never_subsequent_call(self, mock_input):
        """Test subsequent call to never-prompted question skips prompting"""
        io = InputOutput(pretty=False, fancy_input=False)
        io.never_prompts.add(("Are you sure?", None))
        result = asyncio.run(io.confirm_ask("Are you sure?", allow_never=True))
        assert not result
        mock_input.assert_not_called()

    @patch("builtins.input", side_effect=["d"])
    def test_confirm_ask_allow_never_with_subject(self, mock_input):
        """Test 'don't ask again' with subject parameter"""
        io = InputOutput(pretty=False, fancy_input=False)
        result = asyncio.run(
            io.confirm_ask("Confirm action?", subject="Subject Text", allow_never=True)
        )
        assert not result
        mock_input.assert_called_once()
        assert ("Confirm action?", "Subject Text") in io.never_prompts

    @patch("builtins.input")
    def test_confirm_ask_allow_never_subject_subsequent_call(self, mock_input):
        """Test subsequent call with same question and subject skips prompting"""
        io = InputOutput(pretty=False, fancy_input=False)
        io.never_prompts.add(("Confirm action?", "Subject Text"))
        result = asyncio.run(
            io.confirm_ask("Confirm action?", subject="Subject Text", allow_never=True)
        )
        assert not result
        mock_input.assert_not_called()

    @patch("builtins.input", side_effect=["d", "n"])
    def test_confirm_ask_allow_never_false_not_stored(self, mock_input):
        """Test allow_never=False does not add to never_prompts"""
        io = InputOutput(pretty=False, fancy_input=False)
        result = asyncio.run(io.confirm_ask("Do you want to proceed?", allow_never=False))
        assert not result
        assert mock_input.call_count == 2
        assert ("Do you want to proceed?", None) not in io.never_prompts


class TestInputOutputMultilineMode:
    @pytest.fixture(autouse=True)
    def setup(self, gpt35_model):
        self.GPT35 = gpt35_model
        self.io = InputOutput(fancy_input=True)
        self.io.prompt_session = MagicMock()

    def test_toggle_multiline_mode(self):
        """Test that toggling multiline mode works correctly"""
        # Start in single-line mode
        self.io.multiline_mode = False

        # Toggle to multiline mode
        self.io.toggle_multiline_mode()
        assert self.io.multiline_mode

        # Toggle back to single-line mode
        self.io.toggle_multiline_mode()
        assert not self.io.multiline_mode

    def test_tool_message_unicode_fallback(self):
        """Test that Unicode messages are properly converted to ASCII with replacement"""
        io = InputOutput(pretty=False, fancy_input=False)

        # Create a message with invalid Unicode that can't be encoded in UTF-8
        # Using a surrogate pair that's invalid in UTF-8
        invalid_unicode = "Hello \ud800World"

        # Mock console.print to capture the output
        with patch.object(io.console, "print") as mock_print:
            # First call will raise UnicodeEncodeError
            mock_print.side_effect = [UnicodeEncodeError("utf-8", "", 0, 1, "invalid"), None]

            io._tool_message(invalid_unicode)

            # Verify that the message was converted to ASCII with replacement
            assert mock_print.call_count == 2
            args, kwargs = mock_print.call_args
            converted_message = args[0]

            # The invalid Unicode should be replaced with '?'
            assert converted_message == "Hello ?World"

    async def test_multiline_mode_restored_after_interrupt(self):
        """Test that multiline mode is restored after KeyboardInterrupt"""
        io = InputOutput(fancy_input=True)
        io.prompt_session = MagicMock()
        await Coder.create(self.GPT35, None, io)

        # Use AsyncMock for prompt_async (for confirm_ask)
        io.prompt_session.prompt_async = AsyncMock(side_effect=KeyboardInterrupt)

        # Start in multiline mode
        io.multiline_mode = True

        # Test confirm_ask() - this is now async, so we need to handle it differently
        with pytest.raises(KeyboardInterrupt):
            await io.confirm_ask("Test question?")
        assert io.multiline_mode  # Should be restored

        # Test prompt_ask() - this is still synchronous
        # Mock the synchronous prompt method to raise KeyboardInterrupt
        io.prompt_session.prompt = MagicMock(side_effect=KeyboardInterrupt)

        with pytest.raises(KeyboardInterrupt):
            io.prompt_ask("Test prompt?")
        assert io.multiline_mode  # Should be restored

    async def test_multiline_mode_restored_after_normal_exit(self):
        """Test that multiline mode is restored after normal exit"""
        io = InputOutput(fancy_input=True)
        io.prompt_session = MagicMock()
        await Coder.create(self.GPT35, None, io)

        # Use AsyncMock for prompt_async that returns "y"
        io.prompt_session.prompt_async = AsyncMock(return_value="y")

        # Start in multiline mode
        io.multiline_mode = True

        # Test confirm_ask() - this is now async
        await io.confirm_ask("Test question?")
        assert io.multiline_mode  # Should be restored

        # Test prompt_ask() - this is still synchronous
        io.prompt_ask("Test prompt?")
        assert io.multiline_mode  # Should be restored

    def test_ensure_hash_prefix(self):
        """Test that ensure_hash_prefix correctly adds # to valid hex colors"""
        from cecli.io import ensure_hash_prefix

        # Test valid hex colors without #
        assert ensure_hash_prefix("000") == "#000"
        assert ensure_hash_prefix("fff") == "#fff"
        assert ensure_hash_prefix("F00") == "#F00"
        assert ensure_hash_prefix("123456") == "#123456"
        assert ensure_hash_prefix("abcdef") == "#abcdef"
        assert ensure_hash_prefix("ABCDEF") == "#ABCDEF"

        # Test hex colors that already have #
        assert ensure_hash_prefix("#000") == "#000"
        assert ensure_hash_prefix("#123456") == "#123456"

        # Test invalid inputs (should return unchanged)
        assert ensure_hash_prefix("") == ""
        assert ensure_hash_prefix(None) is None
        assert ensure_hash_prefix("red") == "red"  # Named color
        assert ensure_hash_prefix("12345") == "12345"  # Wrong length
        assert ensure_hash_prefix("1234567") == "1234567"  # Wrong length
        assert ensure_hash_prefix("xyz") == "xyz"  # Invalid hex chars
        assert ensure_hash_prefix("12345g") == "12345g"  # Invalid hex chars

    def test_tool_output_color_handling(self):
        """Test that tool_output correctly handles hex colors without # prefix"""
        from unittest.mock import patch

        # Create IO with hex color without # for tool_output_color
        io = InputOutput(tool_output_color="FFA500", pretty=True)

        # Patch console.print to avoid actual printing
        with patch.object(io.console, "print") as mock_print:
            # This would raise ColorParseError without the fix
            io.tool_output("Test message")

            # Verify the call was made without error
            mock_print.assert_called_once()

            # Verify the style was correctly created with # prefix
            # The first argument is the message, second would be the style
            kwargs = mock_print.call_args.kwargs
            assert "style" in kwargs

        # Test with other hex color
        io = InputOutput(tool_output_color="00FF00", pretty=True)
        with patch.object(io.console, "print") as mock_print:
            io.tool_output("Test message")
            mock_print.assert_called_once()


@patch("cecli.io.is_dumb_terminal", return_value=False)
@patch.dict(os.environ, {"NO_COLOR": ""})
class TestInputOutputFormatFiles:
    def test_format_files_for_input_pretty_false(self, mock_is_dumb_terminal):
        io = InputOutput(pretty=False, fancy_input=False)
        rel_fnames = ["file1.txt", "file[markup].txt", "ro_file.txt"]
        rel_read_only_fnames = ["ro_file.txt"]
        rel_read_only_stub_fnames = []

        expected_output = "file1.txt\nfile[markup].txt\nro_file.txt (read only)\n"
        # Sort the expected lines because the order of editable vs read-only might vary
        # depending on internal sorting, but the content should be the same.
        # The method sorts editable_files and read_only_files separately.
        # The final output joins sorted(read_only_files) + sorted(editable_files)

        # Based on current implementation:
        # read_only_files = ["ro_file.txt (read only)"]
        # editable_files = ["file1.txt", "file[markup].txt"]
        # output = "\n".join(read_only_files + editable_files) + "\n"

        # Correct expected output based on implementation:
        expected_output_lines = sorted(
            [
                "ro_file.txt (read only)",
                "file1.txt",
                "file[markup].txt",
            ]
        )
        expected_output = "\n".join(expected_output_lines) + "\n"

        actual_output = io.format_files_for_input(
            rel_fnames, rel_read_only_fnames, rel_read_only_stub_fnames
        )

        # Normalizing actual output by splitting, sorting, and rejoining
        actual_output_lines = sorted(filter(None, actual_output.splitlines()))
        normalized_actual_output = "\n".join(actual_output_lines) + "\n"

        assert normalized_actual_output == expected_output

    @patch("cecli.io.Columns")
    @patch("os.path.abspath")
    @patch("os.path.join")
    def test_format_files_for_input_pretty_true_no_files(
        self, mock_join, mock_abspath, mock_columns, mock_is_dumb_terminal
    ):
        io = InputOutput(pretty=True, root="test_root")
        io.format_files_for_input([], [], [])
        mock_columns.assert_not_called()

    @patch("cecli.io.Columns")
    @patch("os.path.abspath")
    @patch("os.path.join")
    def test_format_files_for_input_pretty_true_editable_only(
        self, mock_join, mock_abspath, mock_columns, mock_is_dumb_terminal
    ):
        io = InputOutput(pretty=True, root="test_root")
        rel_fnames = ["edit1.txt", "edit[markup].txt"]

        io.format_files_for_input(rel_fnames, [], [])

        mock_columns.assert_called_once()
        args, _ = mock_columns.call_args
        renderables = args[0]

        assert len(renderables) == 2
        assert renderables[0] == "edit1.txt"
        assert renderables[1] == "edit[markup].txt"

    @patch("cecli.io.Columns")
    @patch("os.path.abspath")
    @patch("os.path.join")
    def test_format_files_for_input_pretty_true_readonly_only(
        self, mock_join, mock_abspath, mock_columns, mock_is_dumb_terminal
    ):
        io = InputOutput(pretty=True, root="test_root")

        # Mock path functions to ensure rel_path is chosen by the shortener logic
        mock_join.side_effect = lambda *args: "/".join(args)
        mock_abspath.side_effect = lambda p: "/ABS_PREFIX_VERY_LONG/" + os.path.normpath(p)

        rel_read_only_fnames = ["ro1.txt", "ro[markup].txt"]
        # When all files in chat are read-only
        rel_fnames = list(rel_read_only_fnames)
        rel_read_only_stub_fnames = []

        io.format_files_for_input(rel_fnames, rel_read_only_fnames, rel_read_only_stub_fnames)

        assert mock_columns.call_count == 2
        args, _ = mock_columns.call_args
        renderables = args[0]

        assert len(renderables) == 3  # Readonly: + 2 files
        assert renderables[0] == "Readonly:"
        assert renderables[1] == "ro1.txt"
        assert renderables[2] == "ro[markup].txt"

    @patch("cecli.io.Columns")
    @patch("os.path.abspath")
    @patch("os.path.join")
    def test_format_files_for_input_pretty_true_readonly_stub_only(
        self, mock_join, mock_abspath, mock_columns, mock_is_dumb_terminal
    ):
        io = InputOutput(pretty=True, root="test_root")

        # Mock path functions to ensure rel_path is chosen by the shortener logic
        mock_join.side_effect = lambda *args: "/".join(args)
        mock_abspath.side_effect = lambda p: "/ABS_PREFIX_VERY_LONG/" + os.path.normpath(p)

        rel_read_only_fnames = []
        rel_read_only_stub_fnames = ["ro1.txt", "ro[markup].txt"]
        # When all files in chat are read-only
        rel_fnames = list(rel_read_only_stub_fnames)

        io.format_files_for_input(rel_fnames, rel_read_only_fnames, rel_read_only_stub_fnames)

        assert mock_columns.call_count == 2
        args, _ = mock_columns.call_args
        renderables = args[0]

        assert len(renderables) == 3  # Readonly: + 2 files
        assert renderables[0] == "Readonly:"
        assert renderables[1] == "ro1.txt (stub)"
        assert renderables[2] == "ro[markup].txt (stub)"

    @patch("cecli.io.Columns")
    @patch("os.path.abspath")
    @patch("os.path.join")
    def test_format_files_for_input_pretty_true_mixed_files(
        self, mock_join, mock_abspath, mock_columns, mock_is_dumb_terminal
    ):
        io = InputOutput(pretty=True, root="test_root")

        mock_join.side_effect = lambda *args: "/".join(args)
        mock_abspath.side_effect = lambda p: "/ABS_PREFIX_VERY_LONG/" + os.path.normpath(p)

        rel_fnames = ["edit1.txt", "edit[markup].txt", "ro1.txt", "ro[markup].txt"]
        rel_read_only_fnames = ["ro1.txt", "ro[markup].txt"]
        rel_read_only_stub_fnames = []

        io.format_files_for_input(rel_fnames, rel_read_only_fnames, rel_read_only_stub_fnames)

        assert mock_columns.call_count == 4

        # Check arguments for the first rendering of read-only files (call 0)
        args_ro, _ = mock_columns.call_args_list[0]
        renderables_ro = args_ro[0]
        assert renderables_ro == ["Readonly:", "ro1.txt", "ro[markup].txt"]

        # Check arguments for the first rendering of editable files (call 2)
        args_ed, _ = mock_columns.call_args_list[2]
        renderables_ed = args_ed[0]
        assert renderables_ed == ["Editable:", "edit1.txt", "edit[markup].txt"]
