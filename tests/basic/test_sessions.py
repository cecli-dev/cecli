import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest import TestCase, mock

from cecli.coders import Coder
from cecli.commands import Commands, SwitchCoderSignal
from cecli.helpers.file_searcher import handle_core_files
from cecli.io import InputOutput
from cecli.models import Model
from cecli.utils import GitTemporaryDirectory


class TestSessionCommands(TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.tempdir = tempfile.mkdtemp()
        os.chdir(self.tempdir)
        self.GPT35 = Model("gpt-3.5-turbo")

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.tempdir, ignore_errors=True)

    async def test_cmd_save_session_basic(self):
        """Test basic session save functionality"""
        with GitTemporaryDirectory() as repo_dir:
            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            coder = await Coder.create(self.GPT35, None, io)
            commands = Commands(io, coder)
            test_files = {
                "file1.txt": "Content of file 1",
                "file2.py": "print('Content of file 2')",
                "subdir/file3.md": "# Content of file 3",
            }
            for file_path, content in test_files.items():
                full_path = Path(repo_dir) / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
            commands.execute("add", "file1.txt file2.py")
            commands.execute("read_only", "subdir/file3.md")
            coder.done_messages = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ]
            coder.cur_messages = [{"role": "user", "content": "Can you help me?"}]
            todo_content = "Task 1\nTask 2"
            Path(".cecli.todo.txt").write_text(todo_content, encoding="utf-8")
            session_name = "test_session"
            commands.execute("save_session", session_name)
            session_file = Path(handle_core_files(".cecli")) / "sessions" / f"{session_name}.json"
            self.assertTrue(session_file.exists())
            with open(session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)
            self.assertEqual(session_data["version"], 1)
            self.assertEqual(session_data["session_name"], session_name)
            self.assertEqual(session_data["model"], self.GPT35.name)
            self.assertEqual(session_data["edit_format"], coder.edit_format)
            chat_history = session_data["chat_history"]
            self.assertEqual(chat_history["done_messages"], coder.done_messages)
            self.assertEqual(chat_history["cur_messages"], coder.cur_messages)
            files = session_data["files"]
            self.assertEqual(set(files["editable"]), {"file1.txt", "file2.py"})
            self.assertEqual(set(files["read_only"]), {"subdir/file3.md"})
            self.assertEqual(files["read_only_stubs"], [])
            settings = session_data["settings"]
            self.assertEqual(settings["auto_commits"], coder.auto_commits)
            self.assertEqual(settings["auto_lint"], coder.auto_lint)
            self.assertEqual(settings["auto_test"], coder.auto_test)
            self.assertEqual(session_data["todo_list"], todo_content)

    async def test_cmd_load_session_basic(self):
        """Test basic session load functionality"""
        with GitTemporaryDirectory() as repo_dir:
            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            coder = await Coder.create(self.GPT35, None, io)
            commands = Commands(io, coder)
            test_files = {
                "file1.txt": "Content of file 1",
                "file2.py": "print('Content of file 2')",
                "subdir/file3.md": "# Content of file 3",
            }
            for file_path, content in test_files.items():
                full_path = Path(repo_dir) / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
            session_data = {
                "version": 1,
                "timestamp": time.time(),
                "session_name": "test_session",
                "model": self.GPT35.name,
                "edit_format": "diff",
                "chat_history": {
                    "done_messages": [
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi there!"},
                    ],
                    "cur_messages": [{"role": "user", "content": "Can you help me?"}],
                },
                "files": {
                    "editable": ["file1.txt", "file2.py"],
                    "read_only": ["subdir/file3.md"],
                    "read_only_stubs": [],
                },
                "settings": {"auto_commits": True, "auto_lint": False, "auto_test": False},
                "todo_list": (
                    """Restored tasks
- item"""
                ),
            }
            session_file = Path(handle_core_files(".cecli")) / "sessions" / "test_session.json"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            commands.execute("load_session", "test_session")
            self.assertEqual(coder.done_messages, session_data["chat_history"]["done_messages"])
            self.assertEqual(coder.cur_messages, session_data["chat_history"]["cur_messages"])
            editable_files = {coder.get_rel_fname(f) for f in coder.abs_fnames}
            read_only_files = {coder.get_rel_fname(f) for f in coder.abs_read_only_fnames}
            self.assertEqual(editable_files, {"file1.txt", "file2.py"})
            self.assertEqual(read_only_files, {"subdir/file3.md"})
            self.assertEqual(len(coder.abs_read_only_stubs_fnames), 0)
            self.assertEqual(coder.auto_commits, True)
            self.assertEqual(coder.auto_lint, False)
            self.assertEqual(coder.auto_test, False)
            todo_file = Path(".cecli.todo.txt")
            self.assertTrue(todo_file.exists())
            self.assertEqual(todo_file.read_text(encoding="utf-8"), session_data["todo_list"])

    async def test_cmd_list_sessions_basic(self):
        """Test basic session list functionality"""
        with GitTemporaryDirectory():
            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            coder = await Coder.create(self.GPT35, None, io)
            commands = Commands(io, coder)
            sessions_data = [
                {
                    "version": 1,
                    "timestamp": time.time() - 3600,
                    "session_name": "session1",
                    "model": "gpt-3.5-turbo",
                    "edit_format": "diff",
                    "chat_history": {"done_messages": [], "cur_messages": []},
                    "files": {"editable": [], "read_only": [], "read_only_stubs": []},
                    "settings": {
                        "root": ".",
                        "auto_commits": True,
                        "auto_lint": False,
                        "auto_test": False,
                    },
                },
                {
                    "version": 1,
                    "timestamp": time.time(),
                    "session_name": "session2",
                    "model": "gpt-4",
                    "edit_format": "whole",
                    "chat_history": {"done_messages": [], "cur_messages": []},
                    "files": {"editable": [], "read_only": [], "read_only_stubs": []},
                    "settings": {
                        "root": ".",
                        "auto_commits": True,
                        "auto_lint": False,
                        "auto_test": False,
                    },
                },
            ]
            session_dir = Path(handle_core_files(".cecli")) / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            for session_data in sessions_data:
                session_file = session_dir / f"{session_data['session_name']}.json"
                with open(session_file, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, indent=2, ensure_ascii=False)
            with mock.patch.object(io, "tool_output") as mock_tool_output:
                commands.execute("list_sessions", "")
                calls = mock_tool_output.call_args_list
                self.assertGreater(len(calls), 2)
                output_text = "\n".join([(call[0][0] if call[0] else "") for call in calls])
                self.assertIn("session1", output_text)
                self.assertIn("session2", output_text)
                self.assertIn("gpt-3.5-turbo", output_text)
                self.assertIn("gpt-4", output_text)

    async def test_preserve_todo_list_deprecated(self):
        """Ensure preserve-todo-list flag is deprecated and todo is cleared on startup"""
        with GitTemporaryDirectory():
            todo_path = Path(".cecli.todo.txt")
            todo_path.write_text("keep me", encoding="utf-8")
            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            with mock.patch.object(io, "tool_warning") as mock_tool_warning:
                await Coder.create(self.GPT35, None, io)
            self.assertFalse(todo_path.exists())
            self.assertTrue(
                any("deprecated" in call[0][0] for call in mock_tool_warning.call_args_list)
            )

    async def test_cmd_save_load_session_agent_config(self):
        """Test session save/load for agent-specific configs (mcp, skills, tools)."""
        with GitTemporaryDirectory():
            # Mock args for AgentCoder
            mock_args = mock.MagicMock()
            mock_args.agent_config = json.dumps(
                {
                    "tools_paths": ["/test/tools/path"],
                    "tools_includelist": ["included_tool"],
                    "tools_excludelist": ["excluded_tool"],
                }
            )
            # This is needed for the skills manager to be created
            mock_args.skills_paths = ["/test/skills/path"]
            mock_args.mcp_servers = json.dumps([{"name": "mock_mcp"}])
            mock_args.mcp_servers_files = []
            mock_args.verbose = False
            mock_args.debug = False
            mock_args.tui = False
            mock_args.auto_save_session_name = "auto-save"
            mock_args.auto_save = False
            mock_args.auto_load = False
            mock_args.yes_always_commands = True
            mock_args.command_prefix = None
            mock_args.file_diffs = True
            mock_args.max_reflections = 3
            mock_args.model = "gpt-3.5-turbo"
            mock_args.weak_model = None
            mock_args.editor_model = None
            mock_args.agent_model = None
            mock_args.editor_edit_format = None
            mock_args.retries = None
            mock_args.reasoning_effort = None
            mock_args.thinking_tokens = None
            mock_args.check_model_accepts_settings = True
            mock_args.copy_paste = False
            mock_args.hooks = None

            io = InputOutput(pretty=False, fancy_input=False, yes=True)

            # === SAVE SESSION ===
            coder_to_save = await Coder.create(
                self.GPT35, "agent", io, args=mock_args, repo=mock.MagicMock()
            )
            commands_to_save = Commands(io, coder_to_save, args=mock_args)

            # Configure state to be saved
            await coder_to_save.mcp_manager.connect_server("mock_mcp")
            coder_to_save.skills_manager.include_list = {"included_skill"}
            coder_to_save.skills_manager.exclude_list = {"excluded_skill"}
            coder_to_save.skills_manager.directory_paths = ["/test/skills/path/saved"]

            session_name = "agent_session"
            await commands_to_save.execute("save-session", session_name)

            session_file = Path(handle_core_files(".cecli")) / "sessions" / f"{session_name}.json"
            self.assertTrue(session_file.exists())

            with open(session_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)

            # Assert saved data is correct
            self.assertEqual(saved_data["mcps"], ["mock_mcp"])
            self.assertEqual(saved_data["skills"]["skills_paths"], ["/test/skills/path/saved"])
            self.assertEqual(saved_data["skills"]["skills_includelist"], ["included_skill"])
            self.assertEqual(saved_data["skills"]["skills_excludelist"], ["excluded_skill"])
            self.assertEqual(saved_data["tools"]["tools_paths"], ["/test/tools/path"])
            self.assertEqual(saved_data["tools"]["tools_includelist"], ["included_tool"])
            self.assertEqual(saved_data["tools"]["tools_excludelist"], ["excluded_tool"])

            # === LOAD SESSION ===
            # Create a new coder to load into, ensuring it's a clean slate
            coder_to_load_initial = await Coder.create(
                self.GPT35, "agent", io, args=mock_args, repo=mock.MagicMock()
            )
            commands_to_load = Commands(io, coder_to_load_initial, args=mock_args)

            # Mock ToolRegistry.build_registry to check if it's called
            with mock.patch(
                "cecli.tools.utils.registry.ToolRegistry.build_registry"
            ) as mock_build_registry:
                coder_after_load = None
                try:
                    await commands_to_load.execute("load-session", session_name)
                except SwitchCoderSignal as e:
                    # The SwitchCoderSignal is expected, we need to get the new coder from it
                    coder_after_load = await Coder.create(**e.kwargs)

                self.assertIsNotNone(coder_after_load)

                # Assert loaded state is correct in the new coder instance
                connected_mcps = {s.name for s in coder_after_load.mcp_manager.connected_servers}
                self.assertIn("mock_mcp", connected_mcps)

                self.assertEqual(
                    coder_after_load.skills_manager.directory_paths, ["/test/skills/path/saved"]
                )
                self.assertEqual(coder_after_load.skills_manager.include_list, {"included_skill"})
                self.assertEqual(coder_after_load.skills_manager.exclude_list, {"excluded_skill"})

                self.assertEqual(
                    coder_after_load.agent_config["tools_paths"], ["/test/tools/path"]
                )
                self.assertEqual(
                    coder_after_load.agent_config["tools_includelist"], ["included_tool"]
                )
                self.assertEqual(
                    coder_after_load.agent_config["tools_excludelist"], ["excluded_tool"]
                )

                # Assert that the tool registry was rebuilt
                mock_build_registry.assert_called_with(agent_config=coder_after_load.agent_config)
