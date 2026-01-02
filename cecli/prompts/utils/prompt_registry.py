"""
Central registry for managing all prompts in YAML format.

This module implements a YAML-based prompt inheritance system where:
1. base.yml contains default prompts with `_inherits: []`
2. Specific YAML files can override/extend using `_inherits` key
3. Inheritance chains are resolved recursively (e.g., editor_diff_fenced → editblock_fenced → editblock → base)
4. Prompts are merged in inheritance order (base → intermediate → specific)
5. The `_inherits` key is removed from final merged results
6. Circular dependencies are detected and prevented
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class PromptRegistry:
    """Central registry for loading and managing prompts from YAML files."""

    _instance = None
    _prompts_cache: Dict[str, Dict[str, Any]] = {}
    _base_prompts: Optional[Dict[str, Any]] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptRegistry, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._prompts_dir = Path(__file__).parent / "../../prompts"
            self._initialized = True

    def _load_yaml_file(self, file_path: Path) -> Dict[str, Any]:
        """Load a YAML file and return its contents."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML file {file_path}: {e}")

    def _get_base_prompts(self) -> Dict[str, Any]:
        """Load and cache base.yml prompts."""
        if self._base_prompts is None:
            base_path = self._prompts_dir / "base.yml"
            self._base_prompts = self._load_yaml_file(base_path)
        return self._base_prompts

    def _merge_prompts(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge override dict into base dict."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_prompts(result[key], value)
            else:
                result[key] = value

        return result

    def _resolve_inheritance_chain(
        self, prompt_name: str, visited: Optional[set] = None
    ) -> List[str]:
        """
        Resolve the full inheritance chain for a prompt type.

        Args:
            prompt_name: Name of the prompt type
            visited: Set of already visited prompts to detect circular dependencies

        Returns:
            List of prompt names in inheritance order (from base to most specific)
        """
        if visited is None:
            visited = set()

        if prompt_name in visited:
            raise ValueError(f"Circular dependency detected in prompt inheritance: {prompt_name}")

        visited.add(prompt_name)

        # Special case for base.yml
        if prompt_name == "base":
            return ["base"]

        # Load the prompt file to get its inheritance chain
        prompt_path = self._prompts_dir / f"{prompt_name}.yml"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        prompt_data = self._load_yaml_file(prompt_path)
        inherits = prompt_data.get("_inherits", [])

        # Resolve inheritance chain recursively
        inheritance_chain = []
        for parent in inherits:
            parent_chain = self._resolve_inheritance_chain(parent, visited.copy())
            # Add parent chain, avoiding duplicates while preserving order
            for item in parent_chain:
                if item not in inheritance_chain:
                    inheritance_chain.append(item)

        # Add current prompt to the end of the chain
        if prompt_name not in inheritance_chain:
            inheritance_chain.append(prompt_name)

        return inheritance_chain

    def get_prompt(self, prompt_name: str) -> Dict[str, Any]:
        """
        Get prompts for a specific prompt type.

        Args:
            prompt_name: Name of the prompt type (e.g., "agent", "editblock", "wholefile")

        Returns:
            Dictionary containing all prompt attributes for the specified type
        """
        # Check cache first
        if prompt_name in self._prompts_cache:
            return self._prompts_cache[prompt_name]

        # Resolve inheritance chain
        inheritance_chain = self._resolve_inheritance_chain(prompt_name)

        # Start with empty dict and merge in inheritance order
        merged_prompts: Dict[str, Any] = {}

        for current_name in inheritance_chain:
            # Load prompts for this level
            if current_name == "base":
                current_prompts = self._get_base_prompts()
            else:
                prompt_path = self._prompts_dir / f"{current_name}.yml"
                current_prompts = self._load_yaml_file(prompt_path)

            # Merge current prompts into accumulated result
            merged_prompts = self._merge_prompts(merged_prompts, current_prompts)

        # Remove _inherits key from final result (it's metadata, not a prompt)
        merged_prompts.pop("_inherits", None)

        # Cache the result
        self._prompts_cache[prompt_name] = merged_prompts

        return merged_prompts

    def reload_prompts(self):
        """Clear cache and reload all prompts from disk."""
        self._prompts_cache.clear()
        self._base_prompts = None

    def list_available_prompts(self) -> list[str]:
        """List all available prompt types."""
        prompts = []
        for file_path in self._prompts_dir.glob("*.yml"):
            if file_path.name != "base.yml":
                prompts.append(file_path.stem)
        return sorted(prompts)


# Global instance for easy access
registry = PromptRegistry()
