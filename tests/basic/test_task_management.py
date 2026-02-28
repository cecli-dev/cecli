import os
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from cecli.brainfile import CecliTaskStore
from cecli.coders import Coder
from cecli.commands import Commands
from cecli.io import InputOutput
from cecli.models import Model
from cecli.tools.update_todo_list import Tool as UpdateTodoListTool


class TestTaskManagement(TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.tempdir = tempfile.mkdtemp()
        os.chdir(self.tempdir)
        self.GPT35 = Model("gpt-3.5-turbo")

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.tempdir, ignore_errors=True)

    async def test_task_command_basic_crud_and_open(self):
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)
        active_updates = []
        coder.io.set_active_task = lambda **kwargs: active_updates.append(kwargs)
        commands = Commands(io, coder)
        store = CecliTaskStore(Path(coder.root))

        await commands.execute("task", 'add "Implement OAuth flow"')
        tasks = store.list_tasks("board")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], "task-1")

        await commands.execute("task", "open task 1")
        board_task_path = Path(coder.root) / ".cecli" / "tasks" / "board" / "task-1.md"
        self.assertIn(str(board_task_path.resolve()), coder.abs_fnames)

        await commands.execute("task", 'update task-1 "Implement OAuth callback flow"')
        task_data = store.find_task("task-1")
        self.assertIsNotNone(task_data)
        self.assertEqual(task_data["task"].title, "Implement OAuth callback flow")

        await commands.execute("task", "complete task-1")
        self.assertFalse((Path(coder.root) / ".cecli" / "tasks" / "board" / "task-1.md").exists())
        self.assertTrue((Path(coder.root) / ".cecli" / "tasks" / "logs" / "task-1.md").exists())
        self.assertNotIn(str(board_task_path.resolve()), coder.abs_fnames)
        self.assertIsNone(getattr(coder, "active_task_id", None))
        self.assertEqual(active_updates[-1]["title"], "")

    async def test_task_drop_closes_task_context_without_deleting(self):
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)
        commands = Commands(io, coder)
        store = CecliTaskStore(Path(coder.root))

        created = store.create_task("Refactor auth path")
        task_id = created["id"]
        board_task_path = Path(coder.root) / created["relpath"]

        await commands.execute("task", f"open {task_id}")
        self.assertIn(str(board_task_path.resolve()), coder.abs_fnames)

        await commands.execute("task", "drop")
        self.assertNotIn(str(board_task_path.resolve()), coder.abs_fnames)
        self.assertTrue(
            (Path(coder.root) / ".cecli" / "tasks" / "board" / f"{task_id}.md").exists()
        )

    async def test_open_task_via_command(self):
        """Test opening a task via /task open and verifying context updates."""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)
        store = CecliTaskStore(Path(coder.root))
        active_updates = []
        coder.io.set_active_task = lambda **kwargs: active_updates.append(kwargs)
        commands = Commands(io, coder)

        created = store.create_task("Write API tests")
        task_id = created["id"]
        board_path = Path(coder.root) / created["relpath"]

        await commands.execute("task", f"open {task_id}")
        self.assertIn(str(board_path.resolve()), coder.abs_fnames)
        self.assertGreaterEqual(len(active_updates), 1)
        self.assertEqual(active_updates[-1]["task_id"], task_id)

    async def test_update_todo_list_auto_creates_session_task(self):
        """When no board task exists, UpdateTodoList auto-creates one (no todo.txt)."""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)

        result = UpdateTodoListTool.execute(
            coder,
            tasks=[
                {"task": "Read protocol docs", "done": False, "current": True},
                {"task": "Write summary", "done": False},
            ],
        )
        self.assertIn("subtasks for task-1", result)

        # A board task should have been auto-created
        store = CecliTaskStore(Path(coder.root))
        brainfile_path = os.path.join(coder.root, ".cecli", "tasks", "brainfile.md")
        self.assertTrue(os.path.exists(brainfile_path))

        found = store.find_task("task-1")
        self.assertIsNotNone(found)
        subtasks = found["task"].subtasks
        self.assertEqual(len(subtasks), 2)
        self.assertEqual(subtasks[0].title, "Read protocol docs")

        # active_task_id should be set
        self.assertEqual(getattr(coder, "active_task_id", None), "task-1")

        # No todo.txt should exist
        todo_path = os.path.join(coder.root, ".cecli", "todo.txt")
        self.assertFalse(os.path.isfile(todo_path))

    async def test_update_todo_list_reuses_incomplete_task(self):
        """UpdateTodoList reuses an existing incomplete task instead of creating new."""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)
        store = CecliTaskStore(Path(coder.root))

        # Pre-create a task with incomplete subtasks
        created = store.create_task("Existing work", column="in-progress")
        store.update_task_subtasks(
            created["id"],
            [{"task": "Step 1", "done": True}, {"task": "Step 2", "done": False}],
        )

        # Now call UpdateTodoList without setting active_task_id
        result = UpdateTodoListTool.execute(
            coder,
            tasks=[
                {"task": "Step 2", "done": True},
                {"task": "Step 3", "done": False},
            ],
        )
        self.assertIn("subtasks for task-1", result)
        self.assertEqual(getattr(coder, "active_task_id", None), "task-1")

        # Should NOT have created task-2
        self.assertIsNone(store.find_task("task-2"))

    async def test_update_todo_list_creates_new_after_all_complete(self):
        """When all existing tasks are complete, UpdateTodoList creates a new one."""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)
        store = CecliTaskStore(Path(coder.root))

        # Pre-create a task with all subtasks done
        created = store.create_task("Finished work", column="in-progress")
        store.update_task_subtasks(
            created["id"],
            [{"task": "Done item", "done": True}],
        )

        result = UpdateTodoListTool.execute(
            coder,
            tasks=[{"task": "New work", "done": False}],
        )
        self.assertIn("subtasks for task-2", result)
        self.assertEqual(getattr(coder, "active_task_id", None), "task-2")

    async def test_update_todo_list_routes_to_board_task_when_active(self):
        """When a board task is already active, UpdateTodoList writes to that task's subtasks."""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)
        store = CecliTaskStore(Path(coder.root))
        commands = Commands(io, coder)

        await commands.execute("task", "new Active checklist task")
        result = UpdateTodoListTool.execute(
            coder,
            tasks=[
                {"task": "Read protocol docs", "done": False, "current": True},
                {"task": "Write summary", "done": False},
            ],
        )
        self.assertIn("subtasks for task-1", result)

        found = store.find_task("task-1")
        self.assertIsNotNone(found)
        subtasks = found["task"].subtasks
        self.assertEqual(len(subtasks), 2)
        self.assertEqual(subtasks[0].title, "Read protocol docs")

    async def test_task_new_creates_and_activates(self):
        """/task new creates a fresh task and sets it as active."""
        io = InputOutput(pretty=False, fancy_input=False, yes=True)
        coder = await Coder.create(self.GPT35, None, io)
        active_updates = []
        coder.io.set_active_task = lambda **kwargs: active_updates.append(kwargs)
        commands = Commands(io, coder)

        await commands.execute("task", "new My custom title")

        store = CecliTaskStore(Path(coder.root))
        tasks = store.list_tasks("board")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "My custom title")
        self.assertEqual(getattr(coder, "active_task_id", None), "task-1")
        self.assertGreaterEqual(len(active_updates), 1)
