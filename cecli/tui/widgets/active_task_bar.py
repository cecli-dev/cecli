"""Active task bar widget shown above the footer."""

from textual.widgets import Static


class ActiveTaskBar(Static):
    """Single-line active task indicator."""

    DEFAULT_CSS = """
    ActiveTaskBar {
        height: 1;
        width: 100%;
        color: $secondary;
        background: $surface;
        padding: 0 1;
    }

    ActiveTaskBar.hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.add_class("hidden")

    def update_task(
        self,
        task_id: str = "",
        title: str = "",
        column: str = "",
        subtasks_done: int = 0,
        subtasks_total: int = 0,
        mode: str = "",
        location: str = "",
    ) -> None:
        title = (title or "").strip()
        if not title:
            self.update("")
            self.add_class("hidden")
            return

        progress = (
            f"{subtasks_done}/{subtasks_total}" if subtasks_total and subtasks_total > 0 else "0/0"
        )
        access = "view" if mode == "view" else "edit"
        where = "logs" if location == "logs" else "board"
        text = f"Task: {title} | {column or '-'} | {progress} | {where}:{access}"
        self.update(text)
        self.remove_class("hidden")
