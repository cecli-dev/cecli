from textual.widgets import Static


class KeyHints(Static):
    """Key hints widget."""

    DEFAULT_CSS = """
    KeyHints {
        text-align: right;
        color: $secondary;
        padding: 0 2 0 0;
        height: 1;
        width: 100%;
        margin: 0 0 1 0;
    }
    """
