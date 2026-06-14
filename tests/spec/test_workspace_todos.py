import unittest
from pathlib import Path

from cecli.spec.todos import WorkspaceTodos
from cecli.utils import GitTemporaryDirectory, make_repo


class TestWorkspaceTodos(unittest.TestCase):
    def test_roundtrip(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            item = api.add("Ship feature", template="feature")
            self.assertIn("## Goal", item.spec)
            self.assertTrue(api.path.is_file())
            store = api.load()
            self.assertEqual(len(store.todos), 1)
            self.assertEqual(store.todos[0].title, "Ship feature")
            api.set_active(item.id)
            store = api.load()
            self.assertEqual(store.active_id, item.id)
            api.append_links(["src/foo.ts", "commit:abc123"])
            store = api.load()
            self.assertIn("src/foo.ts", store.todos[0].links)
            api.mark_done(item.id)
            store = api.load()
            self.assertEqual(store.todos[0].status, "done")
            self.assertIsNone(store.active_id)

    def test_move_reorders(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            a = api.add("First")
            b = api.add("Second")
            store = api.load()
            self.assertEqual(store.todos[0].id, b.id)
            api.move(b.id, "down")
            store = api.load()
            self.assertEqual(store.todos[0].id, a.id)
            self.assertEqual(store.todos[1].id, b.id)

    def test_import_spec_files(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            item = api.add("Spec task", template="spec-driven")
            api.sync_spec_files(item)
            spec_dir = api.specs_root / item.id
            (spec_dir / "requirements.md").write_text("### REQ-1\nUpdated", encoding="utf-8")
            loaded = api.import_spec_files(item.id)
            self.assertIn("Updated", loaded.requirements)

    def test_import_spec_files_short_folder_id(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            item = api.add("Spec task")
            full_dir = api.specs_root / item.id
            if full_dir.is_dir():
                import shutil

                shutil.rmtree(full_dir)
            short = item.id[:8]
            spec_dir = api.specs_root / short
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "requirements.md").write_text("### REQ-1\nFrom disk", encoding="utf-8")
            loaded = api.import_spec_files(item.id)
            self.assertIn("From disk", loaded.requirements)

    def test_maybe_import_spec_from_disk_when_layers_empty(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            item = api.add("Spec task")
            full_dir = api.specs_root / item.id
            if full_dir.is_dir():
                import shutil

                shutil.rmtree(full_dir)
            short = item.id[:8]
            spec_dir = api.specs_root / short
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "requirements.md").write_text("### REQ-1\nAuto", encoding="utf-8")
            loaded = api.maybe_import_spec_from_disk(item)
            self.assertIn("Auto", loaded.requirements)

    def test_delete_removes_spec_folder(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            item = api.add("Gone", template="spec-driven")
            api.sync_spec_files(item)
            spec_dir = api.specs_root / item.id
            self.assertTrue(spec_dir.is_dir())
            api.delete(item.id)
            self.assertFalse(spec_dir.is_dir())

    def test_prune_orphan_spec_folders(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            item = api.add("Keep")
            orphan = api.specs_root / "deleted-task-id"
            orphan.mkdir(parents=True)
            (orphan / "requirements.md").write_text("orphan", encoding="utf-8")
            count, ids = api.prune_orphan_spec_folders()
            self.assertEqual(count, 1)
            self.assertEqual(ids, ["deleted-task-id"])
            self.assertFalse(orphan.is_dir())
            self.assertTrue(
                (api.specs_root / item.id).is_dir() or not (api.specs_root / item.id).exists()
            )

    def test_sync_spec_files_writes_layers(self):
        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            api = WorkspaceTodos(root)
            item = api.add("Export task", template="spec-driven")
            item, _ = api.update(item.id, requirements="### REQ-1\nFrom json")
            api.sync_spec_files(item)
            spec_dir = api.specs_root / item.id
            self.assertIn("From json", (spec_dir / "requirements.md").read_text(encoding="utf-8"))

    def test_delete_removes_linked_agent_todo_txt(self):
        from cecli.spec.agent_todos import (
            AgentTodoRow,
            format_agent_todo_txt,
            import_agent_plan_for_workspace,
        )

        with GitTemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_repo(root)
            agent_path = root / ".cecli" / "agents" / "default" / "todo.txt"
            agent_path.parent.mkdir(parents=True, exist_ok=True)
            agent_path.write_text(
                format_agent_todo_txt([AgentTodoRow(text="Ship it", done=False, current=True)]),
                encoding="utf-8",
            )
            store = import_agent_plan_for_workspace(root)
            todo_id = store.todos[0].id
            api = WorkspaceTodos(root)
            api.delete(todo_id)
            store = api.load()
            self.assertEqual(len(store.todos), 0)
            self.assertFalse(agent_path.is_file())


if __name__ == "__main__":
    unittest.main()
