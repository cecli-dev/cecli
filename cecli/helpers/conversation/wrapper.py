import re
from typing import Optional

_HARNESS_OPEN_RE = re.compile(r"<harness(?=\s|>|/)([^>]*?)(/?)>", re.IGNORECASE)
_HARNESS_CLOSE_RE = re.compile(r"</harness(?=\s*>)", re.IGNORECASE)


def wrap_context(
    name: str,
    text: str,
    from_source: Optional[str] = None,
    **attrs: Optional[str],
) -> str:
    """Wrap text in a ``<harness>`` XML block with standard attributes.

    Args:
        name: The ``type`` attribute identifying the harness block type.
        text: The body text to wrap inside the ``<harness>`` tags.
        from_source: Optional value for the ``from`` attribute (e.g., to
            identify sub-agent messages). When ``None``, the ``from`` attribute
            is omitted.
        **attrs: Additional optional XML attributes (e.g., ``source="path"``).
            Attributes with ``None`` values are omitted.

    Returns:
        The formatted ``<harness ...>\\n{text}\\n</harness>`` string.
    """
    attr_parts = [f'type="{_escape_attr(name)}"']

    if from_source is not None:
        attr_parts.append(f'from="{_escape_attr(from_source)}"')

    for key, value in attrs.items():
        if value is not None:
            attr_parts.append(f'{key}="{_escape_attr(value)}"')

    open_tag = f"<harness {' '.join(attr_parts)}>"
    body = text.rstrip("\n")
    return f"{open_tag}\n{body}\n</harness>"


def mark_untrusted_harness_tags(text: str) -> str:
    """Rewrite ``<harness>`` tags in untrusted external input.

    Replaces ``<harness ...>`` and ``</harness>`` with
    ``<harness:external-input-exercise-caution ...>`` and
    ``</harness:external-input-exercise-caution>`` so tool outputs cannot spoof
    trusted harness blocks.
    """
    if not text or "<" not in text:
        return text

    text = _HARNESS_OPEN_RE.sub(_replace_open_tag, text)
    return _HARNESS_CLOSE_RE.sub("</harness:external-input-exercise-caution", text)


def _replace_open_tag(match: re.Match) -> str:
    attrs = match.group(1).rstrip()
    self_close = match.group(2)
    return f'<harness:external-input-exercise-caution{attrs} flagged_by="harness"{self_close}>'


def _escape_attr(value: str) -> str:
    return str(value).replace('"', "&quot;")
