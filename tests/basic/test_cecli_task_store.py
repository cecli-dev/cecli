import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from cecli.brainfile.store import CecliTaskStore, _normalize_task_id


class TestCecliTaskStore(TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.tempdir = tempfile.mkdtemp()
        os.chdir(self.tempdir)

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_initialize_board_creates_brainfile(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.ensure_initialized()

        board_path = Path(self.tempdir) / ".cecli" / "tasks" / "brainfile.md"
        self.assertTrue(board_path.exists())
        content = board_path.read_text(encoding="utf-8")
        self.assertIn("title: cecli tasks", content)
        self.assertIn("type: board", content)

    def test_board_exists_false_before_init(self):
        store = CecliTaskStore(Path(self.tempdir))
        self.assertFalse(store.board_exists())

    def test_board_exists_true_after_init(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.ensure_initialized()
        self.assertTrue(store.board_exists())

    def test_create_and_find_task(self):
        store = CecliTaskStore(Path(self.tempdir))
        created = store.create_task(title="Test task")
        self.assertEqual(created["id"], "task-1")
        self.assertEqual(created["title"], "Test task")

        found = store.find_task("task-1")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], "task-1")
        self.assertEqual(found["task"].title, "Test task")

    def test_complete_task_moves_to_logs(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.create_task(title="Complete me")
        completed = store.complete_task("task-1")
        self.assertEqual(completed["location"], "logs")

        # Should not be in board anymore
        board_path = Path(self.tempdir) / ".cecli" / "tasks" / "board" / "task-1.md"
        self.assertFalse(board_path.exists())
        log_path = Path(self.tempdir) / ".cecli" / "tasks" / "logs" / "task-1.md"
        self.assertTrue(log_path.exists())

    def test_delete_task(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.create_task(title="Delete me")
        deleted = store.delete_task("task-1")
        self.assertEqual(deleted["id"], "task-1")
        self.assertIsNone(store.find_task("task-1"))

    def test_update_task_title_and_column(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.create_task(title="Original")
        updated = store.update_task("task-1", title="Updated", column="in-progress")
        self.assertTrue(updated["changed"])
        self.assertEqual(updated["title"], "Updated")
        self.assertEqual(updated["column"], "in-progress")

    def test_update_task_subtasks(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.create_task(title="With subtasks")
        store.update_task_subtasks(
            "task-1",
            [
                {"task": "Step 1", "done": True},
                {"task": "Step 2", "done": False, "current": True},
                {"task": "Step 3", "done": False},
            ],
        )

        found = store.find_task("task-1")
        self.assertIsNotNone(found)
        subtasks = found["task"].subtasks
        self.assertEqual(len(subtasks), 3)
        # Current items come first among remaining
        self.assertEqual(subtasks[0].title, "Step 2")
        self.assertFalse(subtasks[0].completed)
        self.assertEqual(subtasks[1].title, "Step 3")
        self.assertEqual(subtasks[2].title, "Step 1")
        self.assertTrue(subtasks[2].completed)

    def test_next_task_id(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.create_task(title="First")
        store.create_task(title="Second")
        store.create_task(title="Third")

        next_id = store.next_task_id("task-1")
        self.assertEqual(next_id, "task-2")

        next_id = store.next_task_id("task-2")
        self.assertEqual(next_id, "task-3")

        next_id = store.next_task_id("task-3")
        self.assertIsNone(next_id)

    def test_list_tasks_scopes(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.create_task(title="Active task")
        store.create_task(title="To complete")
        store.complete_task("task-2")

        board = store.list_tasks("board")
        self.assertEqual(len(board), 1)
        self.assertEqual(board[0]["id"], "task-1")

        logs = store.list_tasks("logs")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["id"], "task-2")

        all_tasks = store.list_tasks("all")
        self.assertEqual(len(all_tasks), 2)

    def test_normalize_task_id_accepts_natural_references(self):
        self.assertEqual(_normalize_task_id("11"), "task-11")
        self.assertEqual(_normalize_task_id("task 11"), "task-11")
        self.assertEqual(_normalize_task_id("task11"), "task-11")
        self.assertEqual(_normalize_task_id(".cecli/tasks/board/task-11.md"), "task-11")

    def test_render_task_todo_block(self):
        store = CecliTaskStore(Path(self.tempdir))
        store.create_task(title="Render test")
        store.update_task_subtasks(
            "task-1",
            [
                {"task": "Done item", "done": True},
                {"task": "Current item", "done": False, "current": True},
                {"task": "Pending item", "done": False},
            ],
        )

        block = store.render_task_todo_block("task-1")
        self.assertIsNotNone(block)
        self.assertIn("Active Task Checklist", block)
        self.assertIn("[x] Done item", block)
        self.assertIn("-> Current item", block)
        self.assertIn("- Pending item", block)

    # -- get_or_create_session_task tests ------------------------------------

    def _make_fake_coder(self):
        """Return a minimal object that satisfies get_or_create_session_task."""
        coder = SimpleNamespace(
            root=self.tempdir,
            abs_fnames=set(),
            abs_read_only_fnames=set(),
            abs_read_only_stubs_fnames=set(),
            active_task_id=None,
        )
        coder.abs_root_path = lambda rel: str(Path(self.tempdir) / rel)
        coder.check_added_files = lambda: None

        io = SimpleNamespace()
        io.read_text = lambda path: (
            Path(path).read_text(encoding="utf-8") if Path(path).exists() else None
        )
        io.set_active_task = lambda **kw: None
        io.tool_output = lambda *a, **kw: None
        coder.io = io

        return coder

    def test_get_or_create_session_task_creates_when_none(self):
        store = CecliTaskStore(Path(self.tempdir))
        coder = self._make_fake_coder()

        result = store.get_or_create_session_task(coder)
        self.assertEqual(result["id"], "task-1")
        self.assertEqual(coder.active_task_id, "task-1")

    def test_get_or_create_does_not_leak_file_to_context(self):
        """Auto-created session task should NOT add file to coder context."""
        store = CecliTaskStore(Path(self.tempdir))
        coder = self._make_fake_coder()

        store.get_or_create_session_task(coder)
        self.assertEqual(len(coder.abs_fnames), 0)
        self.assertEqual(len(coder.abs_read_only_fnames), 0)

    def test_get_or_create_session_task_finds_incomplete(self):
        store = CecliTaskStore(Path(self.tempdir))
        coder = self._make_fake_coder()

        # Pre-create a task with incomplete subtasks
        store.create_task("Existing", column="in-progress")
        store.update_task_subtasks(
            "task-1",
            [{"task": "Not done", "done": False}],
        )

        result = store.get_or_create_session_task(coder)
        self.assertEqual(result["id"], "task-1")
        self.assertEqual(coder.active_task_id, "task-1")
        # Should NOT create task-2
        self.assertIsNone(store.find_task("task-2"))

    def test_get_or_create_session_task_creates_when_all_complete(self):
        store = CecliTaskStore(Path(self.tempdir))
        coder = self._make_fake_coder()

        # Pre-create a task with all subtasks done
        store.create_task("Done task", column="in-progress")
        store.update_task_subtasks(
            "task-1",
            [{"task": "All done", "done": True}],
        )

        result = store.get_or_create_session_task(coder)
        # Should create a new task since all existing are complete
        self.assertEqual(result["id"], "task-2")
        self.assertEqual(coder.active_task_id, "task-2")

    # -- auto_title tests ----------------------------------------------------

    def test_auto_title_from_items(self):
        title = CecliTaskStore.auto_title(
            [
                {"task": "First item", "done": False},
                {"task": "Second item", "done": False},
            ]
        )
        self.assertEqual(title, "First item")

    def test_auto_title_skips_done_items(self):
        title = CecliTaskStore.auto_title(
            [
                {"task": "Done", "done": True},
                {"task": "Not done yet", "done": False},
            ]
        )
        self.assertEqual(title, "Not done yet")

    def test_auto_title_fallback(self):
        from datetime import date

        title = CecliTaskStore.auto_title(None)
        self.assertEqual(title, f"Session {date.today().isoformat()}")

        title = CecliTaskStore.auto_title([])
        self.assertEqual(title, f"Session {date.today().isoformat()}")

        title = CecliTaskStore.auto_title([{"task": "All done", "done": True}])
        self.assertEqual(title, f"Session {date.today().isoformat()}")
