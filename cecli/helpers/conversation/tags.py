from enum import Enum
from typing import Dict


class MessageTag(str, Enum):
    """
    Enumeration of message tags matching current chunk types.

    Fixed set of valid tags matching current chunk types:
    - SYSTEM, STATIC, EXAMPLES, REPO, READONLY_FILES, CHAT_FILES, EDIT_FILES, DIFFS, CUR, DONE, REMINDER
    """

    SYSTEM = "system"
    STATIC = "static"
    EXAMPLES = "examples"
    REPO = "repo"
    RULES = "rules"
    READONLY_FILES = "readonly_files"
    CHAT_FILES = "chat_files"
    EDIT_FILES = "edit_files"
    DIFFS = "diffs"
    LINT = "lint"
    FILE_CONTEXTS = "file_contexts"
    ACTIVE_SKILLS = "active_skills"
    CUR = "cur"
    DONE = "done"
    REMINDER = "reminder"


# Default priority values for each tag type
# Lower priority = earlier in the stream
DEFAULT_TAG_PRIORITY: Dict[MessageTag, int] = {
    MessageTag.SYSTEM: 0,
    MessageTag.STATIC: 50,
    MessageTag.EXAMPLES: 75,
    MessageTag.RULES: 100,
    MessageTag.REPO: 150,
    MessageTag.READONLY_FILES: 200,
    MessageTag.CHAT_FILES: 200,
    MessageTag.EDIT_FILES: 200,
    MessageTag.DIFFS: 200,
    MessageTag.LINT: 200,
    MessageTag.FILE_CONTEXTS: 200,
    MessageTag.DONE: 200,
    MessageTag.CUR: 200,
    MessageTag.ACTIVE_SKILLS: 200,
    MessageTag.REMINDER: 300,
}


# Default timestamp offsets for each tag type
# Used when timestamp is not explicitly provided
DEFAULT_TAG_TIMESTAMP_OFFSET: Dict[MessageTag, int] = {
    MessageTag.SYSTEM: 0,
    MessageTag.STATIC: 0,
    MessageTag.EXAMPLES: 0,
    MessageTag.RULES: 0,
    MessageTag.REPO: 0,
    MessageTag.READONLY_FILES: 0,
    MessageTag.CHAT_FILES: 0,
    MessageTag.EDIT_FILES: 0,
    MessageTag.DIFFS: 0,
    MessageTag.LINT: 0,
    MessageTag.FILE_CONTEXTS: 0,
    MessageTag.DONE: 0,
    MessageTag.CUR: 0,
    MessageTag.ACTIVE_SKILLS: 0,
    MessageTag.REMINDER: 0,
}


def get_default_priority(tag: MessageTag) -> int:
    """Get default priority for a tag type."""
    return DEFAULT_TAG_PRIORITY.get(tag, 200)


def get_default_timestamp_offset(tag: MessageTag) -> int:
    """Get default timestamp offset for a tag type."""
    return DEFAULT_TAG_TIMESTAMP_OFFSET.get(tag, 100_000_000)


def validate_tag(tag: str) -> bool:
    """Validate if a string is a valid tag."""
    try:
        MessageTag(tag)
        return True
    except ValueError:
        return False


def tag_to_chunk_type(tag: MessageTag) -> str:
    """Convert MessageTag to chunk type string for serialization compatibility."""
    return tag.value


def chunk_type_to_tag(chunk_type: str) -> MessageTag:
    """Convert chunk type string to MessageTag."""
    try:
        return MessageTag(chunk_type)
    except ValueError:
        # For backward compatibility, default to CUR for unknown types
        return MessageTag.CUR
