"""Sub-agent configuration parsing.

Parses .md files with YAML front matter to build SubAgentConfig objects.
Pattern matches SkillsManager._parse_skill_metadata().
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import yaml

from cecli.decoding import safe_open


@dataclass
class SubAgentConfig:
    """Configuration for a sub-agent parsed from a .md file."""

    name: str
    prompt: str = ""
    model: Optional[str] = None
    hooks: Dict[str, Any] = field(default_factory=dict)
    auto_reap: Optional[bool] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def parse_subagent_file(file_path: str) -> Optional[SubAgentConfig]:
    """Parse a .md file containing YAML front matter and a system prompt.

    Expected format:
      ---
      name: <agent-name>
      model: <optional-model-override>
      ---
      <system prompt body>

    The ``model`` field supports sentinel placeholders that are resolved
    at runtime to the parent coder's models::

        <weak_model>   - The parent coder's weak model
        <agent_model>  - The parent coder's agent model
        <main_model>   - The parent coder's main model
        <current>      - The currently active (foreground) coder's main model

    Args:
        file_path: Path to the .md file.

    Returns:
        SubAgentConfig if parsing succeeds, None otherwise.
    """

    try:
        with safe_open(file_path, "r") as f:
            content = f.read()
    except (FileNotFoundError, IOError, OSError) as e:
        raise ValueError(f"Cannot read file '{file_path}': {e}")

    # Match YAML front matter between --- markers
    frontmatter_match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE)

    if not frontmatter_match:
        raise ValueError(f"No valid YAML front matter found in '{file_path}'")

    # Parse YAML front matter
    try:
        frontmatter_data = yaml.safe_load(frontmatter_match.group(1))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in '{file_path}': {e}")

    if not isinstance(frontmatter_data, dict):
        raise ValueError(f"Front matter in '{file_path}' must be a mapping")

    name = frontmatter_data.get("name", "")
    if not name:
        raise ValueError(f"'name' field is required in '{file_path}'")

    # Content after front matter becomes the system prompt
    prompt = content[frontmatter_match.end() :].strip()

    # Build config, passing through extra metadata
    hooks_data = frontmatter_data.get("hooks", {})
    if not isinstance(hooks_data, dict):
        hooks_data = {}
    metadata = {
        k: v
        for k, v in frontmatter_data.items()
        if k not in ("name", "model", "hooks", "auto_reap")
    }

    config = SubAgentConfig(
        name=name,
        prompt=prompt,
        model=frontmatter_data.get("model"),
        hooks=hooks_data,
        auto_reap=frontmatter_data.get("auto_reap"),
        metadata=metadata,
    )

    return config
