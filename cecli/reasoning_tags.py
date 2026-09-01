#!/usr/bin/env python

import re

from cecli.dump import dump  # noqa

# Standard tag identifier
REASONING_TAG = "thinking-content-" + "7bbeb8e1441453ad999a0bbba8a46d4b"
# Output formatting
REASONING_START = "--------------\n"
REASONING_END = "----------\n"


def remove_reasoning_content(res, reasoning_tag):
    """
    Remove reasoning content from text based on tags.

    Args:
        res (str): The text to process
        reasoning_tag (str): The tag name to remove

    Returns:
        str: Text with reasoning content removed
    """
    reasoning_tag = unwrap_tag(reasoning_tag)
    if not reasoning_tag:
        return res

    # Try to match the complete tag pattern first
    pattern = f"<{reasoning_tag}>.*?</{reasoning_tag}>"
    res = re.sub(pattern, "", res, flags=re.DOTALL).strip()

    # If closing tag exists but opening tag might be missing, remove everything before closing
    # tag
    closing_tag = f"</{reasoning_tag}>"
    if closing_tag in res:
        # Split on the closing tag and keep everything after it
        parts = res.split(closing_tag, 1)
        res = parts[1].strip() if len(parts) > 1 else res

    return res


def replace_reasoning_tags(text, tag_name):
    """
    Replace opening and closing reasoning tags with standard formatting.
    Content is kept flush with the START and END markers, with exactly one
    blank line after the END marker.

    Args:
        text (str): The text containing the tags
        tag_name (str): The name of the tag to replace

    Returns:
        str: Text with reasoning tags replaced with standard format
    """
    tag_name = unwrap_tag(tag_name)
    if not text:
        return text

    # Replace opening tag with proper spacing
    text = re.sub(f"\\s*<{tag_name}>\\s*", f"\n{REASONING_START}", text)

    # Replace closing tag with proper spacing
    text = re.sub(f"\\s*</{tag_name}>\\s*", f"\n{REASONING_END}\n", text)

    return text


def format_reasoning_content(reasoning_content, tag_name):
    """
    Format reasoning content with appropriate tags.

    Args:
        reasoning_content (str): The content to format
        tag_name (str): The tag name to use

    Returns:
        str: Formatted reasoning content with tags
    """
    tag_name = unwrap_tag(tag_name)
    if not reasoning_content:
        return ""

    formatted = f"<{tag_name}>\n\n{reasoning_content}\n\n</{tag_name}>"
    return formatted


def unwrap_tag(text: str) -> str:
    # Remove any leading/trailing whitespace just in case
    if text:
        clean_text = text.strip()

        # Check if it has both the opening and closing brackets
        if clean_text.startswith("<") and clean_text.endswith(">"):
            # Slice off the first and last characters
            return clean_text[1:-1]

    # Return the original string (or stripped string) if it doesn't match
    return text
