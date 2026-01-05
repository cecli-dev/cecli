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

from typing import Any, Dict, List, Optional

import importlib_resources
import yaml


class PromptObject:
    def __init__(self, prompts_dict):
        for key, value in prompts_dict.items():
            setattr(self, key, value)


class PromptRegistry:
    """Central registry for loading and managing prompts from YAML files."""

    # Class-level state for singleton pattern
    _prompts_cache: Dict[str, Dict[str, Any]] = {}
    _base_prompts: Optional[Dict[str, Any]] = None

    @staticmethod
    def _load_yaml_file(file_name: str) -> Dict[str, Any]:
        """Load a YAML file and return its contents."""
        try:
            # Use importlib_resources to access package files
            file_content = (
                importlib_resources.files("cecli.prompts")
                .joinpath(file_name)
                .read_text(encoding="utf-8")
            )
            return yaml.safe_load(file_content) or {}
        except FileNotFoundError:
            # If not found via importlib_resources, try local file system
            # Treat file_name as absolute path relative to current working directory
            try:
                import os

                file_path = os.path.abspath(file_name)
                if os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        file_content = f.read()
                    return yaml.safe_load(file_content) or {}
                else:
                    raise ValueError(f"Prompt YAML file not found {file_name}")
            except (FileNotFoundError, OSError) as e:
                raise ValueError(f"Error parsing YAML file {file_name}: {e}")
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML file {file_name}: {e}")

    @classmethod
    def _get_base_prompts(cls) -> Dict[str, Any]:
        """Load and cache base.yml prompts."""
        if cls._base_prompts is None:
            cls._base_prompts = cls._load_yaml_file("base.yml")
        return cls._base_prompts

    @staticmethod
    def _merge_prompts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge override dict into base dict."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = PromptRegistry._merge_prompts(result[key], value)
            else:
                result[key] = value

        return result

    @classmethod
    def _resolve_inheritance_chain(
        cls, prompt_name: str, visited: Optional[set] = None
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
        prompt_file_name = f"{prompt_name}.yml"
        try:
            # Check if file exists by trying to access it
            importlib_resources.files("cecli.prompts").joinpath(prompt_file_name).read_text(
                encoding="utf-8"
            )
        except FileNotFoundError:
            # If not found via importlib_resources, try local file system
            # Treat file_name as absolute path relative to current working directory
            try:
                import os

                prompt_file_name = os.path.abspath(prompt_file_name)
                if os.path.exists(prompt_file_name):
                    pass
                else:
                    raise FileNotFoundError(f"Prompt file not found: {prompt_file_name}")
            except (FileNotFoundError, OSError) as e:
                raise FileNotFoundError(f"Prompt file not found: {prompt_file_name}: {e}")

        prompt_data = cls._load_yaml_file(prompt_file_name)
        inherits = prompt_data.get("_inherits", [])

        # Resolve inheritance chain recursively
        inheritance_chain = []
        for parent in inherits:
            parent_chain = cls._resolve_inheritance_chain(parent, visited.copy())
            # Add parent chain, avoiding duplicates while preserving order
            for item in parent_chain:
                if item not in inheritance_chain:
                    inheritance_chain.append(item)

        # Add current prompt to the end of the chain
        if prompt_name not in inheritance_chain:
            inheritance_chain.append(prompt_name)

        return inheritance_chain

    @classmethod
    def get_prompt(cls, prompt_name: str) -> Dict[str, Any]:
        """
        Get prompts for a specific prompt type.

        Args:
            prompt_name: Name of the prompt type (e.g., "agent", "editblock", "wholefile")

        Returns:
            Dictionary containing all prompt attributes for the specified type
        """
        prompt_name = prompt_name.replace(".yml", "")
        # Check cache first
        if prompt_name in cls._prompts_cache:
            return cls._prompts_cache[prompt_name]

        # Resolve inheritance chain
        inheritance_chain = cls._resolve_inheritance_chain(prompt_name)

        # Start with empty dict and merge in inheritance order
        merged_prompts: Dict[str, Any] = {}

        for current_name in inheritance_chain:
            # Load prompts for this level
            if current_name == "base":
                current_prompts = cls._get_base_prompts()
            else:
                current_prompts = cls._load_yaml_file(f"{current_name}.yml")

            # Merge current prompts into accumulated result
            merged_prompts = cls._merge_prompts(merged_prompts, current_prompts)

        # Remove _inherits key from final result (it's metadata, not a prompt)
        merged_prompts.pop("_inherits", None)

        # Cache the result
        cls._prompts_cache[prompt_name] = merged_prompts

        return merged_prompts

    @classmethod
    def reload_prompts(cls):
        """Clear cache and reload all prompts from disk."""
        cls._prompts_cache.clear()
        cls._base_prompts = None

    @staticmethod
    def list_available_prompts() -> list[str]:
        """List all available prompt types."""
        prompts = []
        for path in importlib_resources.files("cecli.prompts").iterdir():
            if path.is_file() and path.name.endswith(".yml") and path.name != "base.yml":
                prompts.append(path.stem)
        return sorted(prompts)


# All methods are static/class methods, so no instance is needed
# Use PromptRegistry.get_prompt() directly
