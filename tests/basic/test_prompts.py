"""
Tests for the prompt inheritance system and prompt registry.

This module tests the YAML-based prompt inheritance system where:
1. base.yml contains default prompts with `_inherits: []`
2. Specific YAML files can override/extend using `_inherits` key
3. Inheritance chains are resolved recursively
4. Prompts are merged in inheritance order (base → intermediate → specific)
5. The `_inherits` key is removed from final merged results
6. Circular dependencies are detected and prevented
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from cecli.prompts.utils.prompt_registry import PromptRegistry


class TestPromptRegistry:
    """Test suite for PromptRegistry class."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create a fresh instance for each test
        self.registry = PromptRegistry.__new__(PromptRegistry)
        self.registry._prompts_dir = Path(__file__).parent / "../../cecli/prompts"
        self.registry._initialized = True
        self.registry._prompts_cache = {}
        self.registry._base_prompts = None

    def test_singleton_pattern(self):
        """Test that PromptRegistry follows singleton pattern."""
        registry1 = PromptRegistry()
        registry2 = PromptRegistry()
        assert registry1 is registry2, "PromptRegistry should be a singleton"

    def test_get_base_prompts(self):
        """Test loading base prompts."""
        base_prompts = self.registry._get_base_prompts()
        assert isinstance(base_prompts, dict)
        assert "_inherits" in base_prompts
        assert base_prompts["_inherits"] == []
        assert "system_reminder" in base_prompts

    def test_load_yaml_file_valid(self):
        """Test loading a valid YAML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"test_key": "test_value", "nested": {"key": "value"}}, f)
            temp_path = f.name

        try:
            result = self.registry._load_yaml_file(Path(temp_path))
            assert result == {"test_key": "test_value", "nested": {"key": "value"}}
        finally:
            os.unlink(temp_path)

    def test_load_yaml_file_not_found(self):
        """Test loading a non-existent YAML file returns empty dict."""
        result = self.registry._load_yaml_file(Path("/nonexistent/path/file.yml"))
        assert result == {}

    def test_load_yaml_file_invalid_yaml(self):
        """Test loading an invalid YAML file raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("invalid: yaml: : :")
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Error parsing YAML file"):
                self.registry._load_yaml_file(Path(temp_path))
        finally:
            os.unlink(temp_path)

    def test_merge_prompts_simple(self):
        """Test simple dictionary merging."""
        base = {"key1": "value1", "key2": "value2"}
        override = {"key2": "new_value2", "key3": "value3"}
        result = self.registry._merge_prompts(base, override)
        expected = {"key1": "value1", "key2": "new_value2", "key3": "value3"}
        assert result == expected

    def test_merge_prompts_nested(self):
        """Test nested dictionary merging."""
        base = {"key1": "value1", "nested": {"a": 1, "b": 2}}
        override = {"nested": {"b": 20, "c": 30}, "key2": "value2"}
        result = self.registry._merge_prompts(base, override)
        expected = {"key1": "value1", "nested": {"a": 1, "b": 20, "c": 30}, "key2": "value2"}
        assert result == expected

    def test_merge_prompts_deep_nested(self):
        """Test deeply nested dictionary merging."""
        base = {"a": {"b": {"c": {"d": 1, "e": 2}}}}
        override = {"a": {"b": {"c": {"e": 20, "f": 30}}}}
        result = self.registry._merge_prompts(base, override)
        expected = {"a": {"b": {"c": {"d": 1, "e": 20, "f": 30}}}}
        assert result == expected

    def test_resolve_inheritance_chain_base(self):
        """Test inheritance chain resolution for base.yml."""
        chain = self.registry._resolve_inheritance_chain("base")
        assert chain == ["base"]

    def test_resolve_inheritance_chain_simple(self):
        """Test inheritance chain resolution for a simple prompt."""
        # Create a temporary directory with test YAML files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create base.yml
            base_path = temp_path / "base.yml"
            with open(base_path, "w") as f:
                yaml.dump({"_inherits": []}, f)

            # Create simple.yml that inherits from base
            simple_path = temp_path / "simple.yml"
            with open(simple_path, "w") as f:
                yaml.dump({"_inherits": ["base"]}, f)

            # Create a test registry with our temp directory
            test_registry = PromptRegistry.__new__(PromptRegistry)
            test_registry._prompts_dir = temp_path
            test_registry._initialized = True
            test_registry._prompts_cache = {}
            test_registry._base_prompts = None

            chain = test_registry._resolve_inheritance_chain("simple")
            assert chain == ["base", "simple"]

    def test_resolve_inheritance_chain_complex(self):
        """Test inheritance chain resolution for a complex prompt."""
        # Create a temporary directory with test YAML files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create base.yml
            base_path = temp_path / "base.yml"
            with open(base_path, "w") as f:
                yaml.dump({"_inherits": []}, f)

            # Create editblock.yml that inherits from base
            editblock_path = temp_path / "editblock.yml"
            with open(editblock_path, "w") as f:
                yaml.dump({"_inherits": ["base"]}, f)

            # Create editblock_fenced.yml that inherits from editblock and base
            editblock_fenced_path = temp_path / "editblock_fenced.yml"
            with open(editblock_fenced_path, "w") as f:
                yaml.dump({"_inherits": ["editblock", "base"]}, f)

            # Create a test registry with our temp directory
            test_registry = PromptRegistry.__new__(PromptRegistry)
            test_registry._prompts_dir = temp_path
            test_registry._initialized = True
            test_registry._prompts_cache = {}
            test_registry._base_prompts = None

            chain = test_registry._resolve_inheritance_chain("editblock_fenced")
            assert chain == ["base", "editblock", "editblock_fenced"]

    def test_resolve_inheritance_chain_circular_dependency(self):
        """Test detection of circular dependencies."""
        # Create a temporary directory with circular YAML files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a.yml that inherits from b.yml
            a_path = temp_path / "a.yml"
            with open(a_path, "w") as f:
                yaml.dump({"_inherits": ["b"]}, f)

            # Create b.yml that inherits from a.yml (circular!)
            b_path = temp_path / "b.yml"
            with open(b_path, "w") as f:
                yaml.dump({"_inherits": ["a"]}, f)

            # Create a test registry with our temp directory
            test_registry = PromptRegistry.__new__(PromptRegistry)
            test_registry._prompts_dir = temp_path
            test_registry._initialized = True
            test_registry._prompts_cache = {}
            test_registry._base_prompts = None

            # Should detect circular dependency
            with pytest.raises(ValueError, match="Circular dependency detected"):
                test_registry._resolve_inheritance_chain("a")

    def test_resolve_inheritance_chain_file_not_found(self):
        """Test error when prompt file doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            self.registry._resolve_inheritance_chain("nonexistent")

    def test_get_prompt_base(self):
        """Test getting base prompts."""
        prompts = self.registry.get_prompt("base")
        assert isinstance(prompts, dict)
        assert "_inherits" not in prompts  # Should be removed
        assert "system_reminder" in prompts
        # Base has empty system_reminder
        assert prompts["system_reminder"] == ""

    def test_get_prompt_editblock(self):
        """Test getting editblock prompts."""
        prompts = self.registry.get_prompt("editblock")
        assert isinstance(prompts, dict)
        assert "_inherits" not in prompts  # Should be removed
        assert "main_system" in prompts
        assert "system_reminder" in prompts
        assert "Act as an expert software developer" in prompts["main_system"]

    def test_get_prompt_patch(self):
        """Test getting patch prompts (inherits from editblock)."""
        prompts = self.registry.get_prompt("patch")
        assert isinstance(prompts, dict)
        assert "_inherits" not in prompts  # Should be removed
        assert "main_system" in prompts
        assert "example_messages" in prompts
        # Patch should have its own system_reminder that overrides editblock's
        assert "V4A Diff Format" in prompts["system_reminder"]

    def test_get_prompt_caching(self):
        """Test that prompts are cached."""
        # Clear cache
        self.registry.reload_prompts()
        assert len(self.registry._prompts_cache) == 0

        # First call should populate cache
        prompts1 = self.registry.get_prompt("editblock")
        assert len(self.registry._prompts_cache) == 1

        # Second call should use cache
        prompts2 = self.registry.get_prompt("editblock")
        assert len(self.registry._prompts_cache) == 1
        assert prompts1 is prompts2  # Same object from cache

    def test_get_prompt_removes_inherits_key(self):
        """Test that _inherits key is removed from final prompts."""
        # Test with a few different prompt types
        for prompt_name in ["base", "editblock", "patch", "editor_diff_fenced"]:
            prompts = self.registry.get_prompt(prompt_name)
            assert "_inherits" not in prompts, f"_inherits key found in {prompt_name}"

    def test_reload_prompts(self):
        """Test that reload_prompts clears cache."""
        # Populate cache
        self.registry.get_prompt("editblock")
        self.registry.get_prompt("patch")
        assert len(self.registry._prompts_cache) == 2

        # Reload should clear cache
        self.registry.reload_prompts()
        assert len(self.registry._prompts_cache) == 0
        assert self.registry._base_prompts is None

    def test_list_available_prompts(self):
        """Test listing available prompts."""
        prompts = self.registry.list_available_prompts()
        assert isinstance(prompts, list)
        assert len(prompts) > 0
        assert "editblock" in prompts
        assert "patch" in prompts
        assert "base" not in prompts  # base.yml should be excluded
        assert all(isinstance(p, str) for p in prompts)

    def test_inheritance_chain_real_example(self):
        """Test a real inheritance chain from the actual YAML files."""
        # Test editor_diff_fenced which has a deep inheritance chain
        chain = self.registry._resolve_inheritance_chain("editor_diff_fenced")
        expected_chain = ["base", "editblock", "editblock_fenced", "editor_diff_fenced"]
        assert chain == expected_chain, f"Expected {expected_chain}, got {chain}"

        # Get the prompts and verify they have expected content
        prompts = self.registry.get_prompt("editor_diff_fenced")
        assert "main_system" in prompts
        assert "system_reminder" in prompts
        assert "go_ahead_tip" in prompts
        assert prompts["go_ahead_tip"] == ""  # editor_diff_fenced overrides this to empty string

    def test_all_prompts_loadable(self):
        """Test that all available prompts can be loaded without errors."""
        prompt_names = self.registry.list_available_prompts()

        for name in prompt_names:
            try:
                prompts = self.registry.get_prompt(name)
                assert isinstance(prompts, dict)
                # Some prompts might be minimal (like copypaste)
                if name != "copypaste":
                    assert len(prompts) > 0, f"Prompt '{name}' is empty"
            except Exception as e:
                pytest.fail(f"Failed to load prompt '{name}': {e}")

    def test_prompt_override_behavior(self):
        """Test that prompt overrides work correctly in inheritance chain."""
        # Get editblock prompts
        editblock_prompts = self.registry.get_prompt("editblock")

        # Get patch prompts (inherits from editblock)
        patch_prompts = self.registry.get_prompt("patch")

        # Patch should have different system_reminder than editblock
        assert editblock_prompts["system_reminder"] != patch_prompts["system_reminder"]

        # But they should share some common fields from base
        assert "files_content_prefix" in editblock_prompts
        assert "files_content_prefix" in patch_prompts
        # The files_content_prefix should be the same (inherited from base)
        assert editblock_prompts["files_content_prefix"] == patch_prompts["files_content_prefix"]


class TestPromptInheritanceIntegration:
    """Integration tests for the prompt inheritance system."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = PromptRegistry()
        self.registry.reload_prompts()

    def test_complete_inheritance_workflow(self):
        """Test complete workflow from YAML files to merged prompts."""
        # Test a prompt with deep inheritance
        prompts = self.registry.get_prompt("editor_diff_fenced")

        # Verify it has content from all levels of inheritance
        assert "main_system" in prompts  # From editblock
        assert "example_messages" in prompts  # From editblock_fenced
        assert "go_ahead_tip" in prompts  # From editor_diff_fenced (overridden to empty string)
        assert "system_reminder" in prompts  # From editblock
        assert "files_content_prefix" in prompts  # From base

        # Verify specific overrides
        assert prompts["go_ahead_tip"] == ""  # editor_diff_fenced overrides this

    def test_yaml_structure_preserved(self):
        """Test that YAML structure (lists, multiline strings) is preserved."""
        # Get editblock prompts which have example_messages list
        prompts = self.registry.get_prompt("editblock")

        assert "example_messages" in prompts
        example_messages = prompts["example_messages"]
        assert isinstance(example_messages, list)
        assert len(example_messages) > 0

        # Check structure of first example message
        first_msg = example_messages[0]
        assert isinstance(first_msg, dict)
        assert "role" in first_msg
        assert "content" in first_msg

        # Check multiline strings are preserved
        assert "\n" in prompts["main_system"]  # Should have newlines


if __name__ == "__main__":
    # Run tests if executed directly
    pytest.main([__file__, "-v"])


class TestPromptInheritanceChains:
    """Test that all prompt inheritance chains are valid and match expected structure."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = PromptRegistry()
        self.registry.reload_prompts()

    def test_all_inheritance_chains_resolvable(self):
        """Test that all inheritance chains can be resolved without errors."""
        prompt_names = self.registry.list_available_prompts()

        for name in prompt_names:
            try:
                chain = self.registry._resolve_inheritance_chain(name)
                assert isinstance(chain, list)
                assert len(chain) > 0
                assert "base" in chain, f"Prompt '{name}' should inherit from base"
                assert chain[-1] == name, f"Last item in chain should be '{name}'"
            except Exception as e:
                pytest.fail(f"Failed to resolve inheritance chain for '{name}': {e}")

    def test_expected_inheritance_chains(self):
        """Test specific inheritance chains that we expect to exist."""
        expected_chains = {
            "base": ["base"],
            "editblock": ["base", "editblock"],
            "editblock_fenced": ["base", "editblock", "editblock_fenced"],
            "editor_diff_fenced": ["base", "editblock", "editblock_fenced", "editor_diff_fenced"],
            "editor_editblock": ["base", "editblock", "editor_editblock"],
            "editor_whole": ["base", "wholefile", "editor_whole"],
            "patch": ["base", "editblock", "patch"],
            "udiff": ["base", "udiff"],  # udiff inherits directly from base
            "udiff_simple": ["base", "udiff", "udiff_simple"],  # udiff_simple inherits from udiff
            "wholefile": ["base", "wholefile"],
            "wholefile_func": ["base", "wholefile_func"],  # inherits directly from base
            "single_wholefile_func": [
                "base",
                "single_wholefile_func",
            ],  # inherits directly from base
            "editblock_func": ["base", "editblock_func"],  # inherits directly from base
            "agent": ["base", "agent"],
            "architect": ["base", "architect"],
            "ask": ["base", "ask"],
            "context": ["base", "context"],
            "copypaste": ["base", "copypaste"],
            "help": ["base", "help"],
        }

        for prompt_name, expected_chain in expected_chains.items():
            if prompt_name == "base":
                continue  # Already tested separately

            try:
                chain = self.registry._resolve_inheritance_chain(prompt_name)
                assert (
                    chain == expected_chain
                ), f"Chain for '{prompt_name}' mismatch. Expected {expected_chain}, got {chain}"
            except FileNotFoundError:
                # Some prompts might not exist in all configurations
                if prompt_name in ["copypaste"]:
                    continue  # copypaste might not exist
                raise
