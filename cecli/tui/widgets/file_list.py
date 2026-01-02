from rich.columns import Columns
from rich.console import Group
from textual.widgets import Static


class FileList(Static):
    """Widget to display the list of files in chat."""

    def update_files(self, chat_files):
        """Update the file list display."""
        if not chat_files:
            self.update("")
            return

        rel_fnames = chat_files.get("rel_fnames", [])
        rel_read_only_fnames = chat_files.get("rel_read_only_fnames", [])
        rel_read_only_stubs_fnames = chat_files.get("rel_read_only_stubs_fnames", [])

        total_files = (
            len(rel_fnames)
            + len(rel_read_only_fnames or [])
            + len(rel_read_only_stubs_fnames or [])
        )

        if total_files == 0:
            self.add_class("empty")
            self.update("")
            return
        else:
            self.remove_class("empty")

        # For very large numbers of files, use a summary display
        if total_files > 20:
            read_only_count = len(rel_read_only_fnames or [])
            stub_file_count = len(rel_read_only_stubs_fnames or [])
            editable_count = len([f for f in rel_fnames if f not in (rel_read_only_fnames or [])])

            summary = f"{editable_count} editable file(s)"
            if read_only_count > 0:
                summary += f", {read_only_count} read-only file(s)"
            if stub_file_count > 0:
                summary += f", {stub_file_count} stub file(s)"
            summary += " (use /ls to list all files)"
            self.update(summary)
            return

        renderables = []

        # Handle read-only files
        if rel_read_only_fnames or rel_read_only_stubs_fnames:
            ro_paths = []
            # Regular read-only files
            for rel_path in sorted(rel_read_only_fnames or []):
                ro_paths.append(rel_path)
            # Stub files with (stub) marker
            for rel_path in sorted(rel_read_only_stubs_fnames or []):
                ro_paths.append(f"{rel_path} (stub)")

            if ro_paths:
                files_with_label = ["Readonly:"] + ro_paths
                renderables.append(Columns(files_with_label))

        # Handle editable files
        editable_files = [
            f
            for f in sorted(rel_fnames)
            if f not in rel_read_only_fnames and f not in rel_read_only_stubs_fnames
        ]
        if editable_files:
            files_with_label = editable_files
            if rel_read_only_fnames or rel_read_only_stubs_fnames:
                files_with_label = ["Editable:"] + editable_files

            renderables.append(Columns(files_with_label))

        self.update(Group(*renderables))
