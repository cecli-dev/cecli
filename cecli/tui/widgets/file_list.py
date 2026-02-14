from rich.columns import Columns
from rich.console import Group
from textual.widgets import Static


class FileList(Static):
    """Widget to display the list of files in chat."""

    chat_files = None

    def update_files(self, chat_files):
        """Update the file list display."""
        self.chat_files = chat_files

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

        # Get available width
        try:
            available_width = self.app.size.width
        except Exception:
            available_width = 80

        # Calculate text width for each section
        show_readonly_summary = False
        show_editable_summary = False

        # Handle read-only files
        ro_paths = []
        if rel_read_only_fnames or rel_read_only_stubs_fnames:
            # Regular read-only files
            for rel_path in sorted(rel_read_only_fnames or []):
                ro_paths.append(rel_path)
            # Stub files with (stub) marker
            for rel_path in sorted(rel_read_only_stubs_fnames or []):
                ro_paths.append(f"{rel_path} (stub)")

            if ro_paths:
                # Calculate total characters needed for readonly section
                # "Readonly:" label + sum of all path lengths
                total_chars = len("Readonly:") + sum(len(path) for path in ro_paths)
                # Account for padding (12 chars total across 2 rows) and spaces between files (n-1)
                # Total available characters across 2 rows = available_width * 2
                # If total_chars > available_width * 2 - 12 - (n-1), show summary
                total_available = available_width * 1.5 - 12 - (len(ro_paths) - 1)

                # If total_available is negative or zero, definitely show summary
                if total_available <= 0 or total_chars > total_available:
                    show_readonly_summary = True

        # Handle editable files
        editable_files = [
            f
            for f in sorted(rel_fnames)
            if f not in rel_read_only_fnames and f not in rel_read_only_stubs_fnames
        ]

        if editable_files:
            # Calculate total characters needed for editable section
            show_editable_label = bool(rel_read_only_fnames or rel_read_only_stubs_fnames)
            total_chars = sum(len(path) for path in editable_files)
            if show_editable_label:
                total_chars += len("Editable:")

            # Account for padding (12 chars total across 2 rows) and spaces between files (n-1)
            # Total available characters across 2 rows = available_width * 2

            total_available = available_width * 1.5 - 12 - (len(editable_files) - 1)

            # If total_available is negative or zero, definitely show summary
            if total_available <= 0 or total_chars > total_available:
                show_editable_summary = True

        # If either section needs summary, show overall summary
        if show_readonly_summary or show_editable_summary or total_files > 20:
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
        if ro_paths and not show_readonly_summary:
            files_with_label = ["Readonly:"] + ro_paths
            renderables.append(Columns(files_with_label))

        # Handle editable files
        if editable_files and not show_editable_summary:
            files_with_label = editable_files
            if rel_read_only_fnames or rel_read_only_stubs_fnames:
                files_with_label = ["Editable:"] + editable_files

            renderables.append(Columns(files_with_label))

        self.update(Group(*renderables))
