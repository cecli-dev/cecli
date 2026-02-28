import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest import TestCase, mock

from cecli.coders import Coder
from cecli.commands import Commands
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
            self.assertNotIn("todo_list", session_data)

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
                "settings": {
                    "auto_commits": True,
                    "auto_lint": False,
                    "auto_test": False,
                },
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

    async def test_session_saves_and_restores_active_task_id(self):
        """Session save/load round-trips active_task_id."""
        with GitTemporaryDirectory():
            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            coder = await Coder.create(self.GPT35, None, io)
            commands = Commands(io, coder)

            # Create a task and set as active
            from cecli.brainfile import CecliTaskStore

            store = CecliTaskStore(Path(coder.root))
            store.create_task("Persist me", column="in-progress")
            store.open_task_in_context(coder, "task-1", mode="auto", explicit=False)
            self.assertEqual(getattr(coder, "active_task_id", None), "task-1")

            # Save session
            commands.execute("save_session", "task_session")
            session_file = Path(coder.root) / ".cecli" / "sessions" / "task_session.json"
            self.assertTrue(session_file.exists())

            with open(session_file, "r") as f:
                data = json.load(f)
            self.assertEqual(data["active_task_id"], "task-1")

            # Clear active task, then restore
            setattr(coder, "active_task_id", None)
            commands.execute("load_session", "task_session")
            self.assertEqual(getattr(coder, "active_task_id", None), "task-1")

    async def test_session_restore_clears_missing_active_task(self):
        """Session restore clears active_task_id if task file is gone."""
        with GitTemporaryDirectory():
            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            coder = await Coder.create(self.GPT35, None, io)
            commands = Commands(io, coder)

            # Write a session file that references a task that doesn't exist
            session_data = {
                "version": 1,
                "session_name": "stale_task",
                "model": self.GPT35.name,
                "edit_format": "diff",
                "chat_history": {"done_messages": [], "cur_messages": []},
                "files": {"editable": [], "read_only": [], "read_only_stubs": []},
                "settings": {
                    "auto_commits": True,
                    "auto_lint": False,
                    "auto_test": False,
                },
                "active_task_id": "task-99",
            }
            session_dir = Path(coder.root) / ".cecli" / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_file = session_dir / "stale_task.json"
            with open(session_file, "w") as f:
                json.dump(session_data, f)

            commands.execute("load_session", "stale_task")
            self.assertIsNone(getattr(coder, "active_task_id", None))

    async def test_tasks_board_persists_on_startup(self):
        """Ensure `.cecli/tasks` data is not cleared on startup."""
        with GitTemporaryDirectory():
            task_path = Path(".cecli/tasks/board/task-1.md")
            task_path.parent.mkdir(parents=True, exist_ok=True)
            task_path.write_text(
                """---
id: task-1
title: Keep me
column: in-progress
subtasks:
  - id: task-1-1
    title: item
    completed: false
---
## Description
Persist this file.
""",
                encoding="utf-8",
            )
            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            await Coder.create(self.GPT35, None, io)
            self.assertTrue(task_path.exists())
