"""Helpers for composer completion parsing."""


def find_at_mention(text: str) -> tuple[int, str, bool] | None:
    """Return the active ``@`` mention in text, if one is being typed.

    A mention starts at the last ``@`` and ends at the first whitespace. When
    the mention starts with ``@"`` it instead ends at the next double quote.

    Returns:
        tuple[int, str, bool] | None: ``(start, prefix, quoted)`` where start
            is the index of the ``@`` and prefix is the text after it. Returns
            None when there is no mention or the mention is already closed.
    """
    at_index = text.rfind("@")
    if at_index < 0:
        return None

    rest = text[at_index + 1 :]
    if rest.startswith('"'):
        closing_quote = rest.find('"', 1)
        if closing_quote != -1:
            return None

        return at_index, rest[1:], True

    if any(char.isspace() for char in rest):
        return None

    return at_index, rest, False
