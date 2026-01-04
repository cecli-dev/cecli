"""
Tests for cecli/tools/helper/registry.py
"""

import sys
from pathlib import Path

from cecli.tools.utils.registry import ToolRegistry

# Add the project root to the path so we can import cecli modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestToolRegistry:
    """Test suite for ToolRegistry class"""

    def setup_method(self):
        """Set up test environment"""
        # Clear and reinitialize the registry to ensure clean state
        ToolRegistry._tools.clear()
        ToolRegistry.initialize_registry()

    def test_registry_initialization(self):
        """Test that registry is properly initialized"""
        # Registry should have tools after initialization
        tools = ToolRegistry.list_tools()
        assert len(tools) > 0, "Registry should have tools after initialization"

        # Check that essential tools are registered
        essential_tools = {"contextmanager", "replacetext", "finished"}
        for tool in essential_tools:
            assert tool in tools, f"Essential tool {tool} should be registered"

    def test_get_tool(self):
        """Test getting individual tools by name"""
        # Get existing tool
        tool_class = ToolRegistry.get_tool("contextmanager")
        assert tool_class is not None, "Should get contextmanager tool"
        assert hasattr(tool_class, "NORM_NAME"), "Tool class should have NORM_NAME"
        assert tool_class.NORM_NAME == "contextmanager", "Tool name should match"

        # Get non-existent tool
        non_existent = ToolRegistry.get_tool("nonexistenttool")
        assert non_existent is None, "Should return None for non-existent tool"

    def test_build_registry_empty_config(self):
        """Test building registry with empty config"""
        registry = ToolRegistry.build_registry({})

        # Should include all tools (except possibly skill tools)
        assert len(registry) > 0, "Should return tools with empty config"

        # Essential tools should always be included
        assert "contextmanager" in registry, "Essential tool should be included"
        assert "replacetext" in registry, "Essential tool should be included"
        assert "finished" in registry, "Essential tool should be included"

    def test_build_registry_with_includelist(self):
        """Test filtering with tools_includelist"""
        config = {"tools_includelist": ["contextmanager", "replacetext", "finished"]}
        registry = ToolRegistry.build_registry(config)

        # Should only include tools in the includelist
        assert len(registry) == 3, "Should only include tools from includelist"
        assert "contextmanager" in registry
        assert "replacetext" in registry
        assert "finished" in registry
        assert "command" not in registry, "Should not include tools not in includelist"

    def test_build_registry_with_excludelist(self):
        """Test filtering with tools_excludelist"""
        config = {"tools_excludelist": ["command", "commandinteractive"]}
        registry = ToolRegistry.build_registry(config)

        # Should exclude specified tools (except essentials)
        assert "command" not in registry, "Should exclude command"
        assert "commandinteractive" not in registry, "Should exclude commandinteractive"
        assert "contextmanager" in registry, "Essential tool should still be included"

    def test_build_registry_exclude_essential(self):
        """Test that essential tools cannot be excluded"""
        config = {"tools_excludelist": ["contextmanager", "replacetext", "finished", "command"]}
        registry = ToolRegistry.build_registry(config)

        # Essential tools should still be included despite excludelist
        assert "contextmanager" in registry, "Essential tool cannot be excluded"
        assert "replacetext" in registry, "Essential tool cannot be excluded"
        assert "finished" in registry, "Essential tool cannot be excluded"
        assert "command" not in registry, "Non-essential tool should be excluded"

    def test_build_registry_combined_filters(self):
        """Test combined filtering with includelist and excludelist"""
        config = {
            "tools_includelist": ["contextmanager", "replacetext", "finished", "command"],
            "tools_excludelist": ["commandinteractive"],
        }
        registry = ToolRegistry.build_registry(config)

        # Should respect all filters
        assert len(registry) == 4, "Should include exactly 4 tools"
        assert "contextmanager" in registry
        assert "replacetext" in registry
        assert "finished" in registry
        assert "command" in registry
        assert "commandinteractive" not in registry

    def test_get_filtered_tools(self):
        """Test get_filtered_tools method"""
        config = {"tools_includelist": ["contextmanager", "replacetext"]}
        ToolRegistry.build_registry(config)
        tool_names = ToolRegistry.get_registered_tools()

        # Should return list of tool names
        assert isinstance(tool_names, list)
        # Should include contextmanager, replacetext, and finished (essential)
        assert len(tool_names) == 3
        assert "contextmanager" in tool_names
        assert "replacetext" in tool_names
        assert "finished" in tool_names  # Essential tool always included

    def test_legacy_config_names(self):
        """Test backward compatibility with legacy config names (whitelist/blacklist)"""
        config = {
            "tools_whitelist": ["contextmanager", "replacetext"],
            "tools_blacklist": ["command"],
        }
        registry = ToolRegistry.build_registry(config)

        # Should work with legacy names
        assert "contextmanager" in registry
        assert "replacetext" in registry
        assert "command" not in registry

    def test_config_precedence(self):
        """Test that new config names take precedence over legacy names"""
        config = {
            "tools_includelist": ["contextmanager"],
            "tools_whitelist": ["command"],  # Should be ignored
            "tools_excludelist": ["commandinteractive"],
            "tools_blacklist": ["finished"],  # Should be ignored for essential tool
        }
        registry = ToolRegistry.build_registry(config)

        # New names should take precedence
        assert "contextmanager" in registry, "Should use tools_includelist"
        assert (
            "command" not in registry
        ), "Should not use tools_whitelist when tools_includelist present"
        assert "commandinteractive" not in registry, "Should use tools_excludelist"
        assert "finished" in registry, "Essential tool cannot be excluded"

    def test_registry_consistency(self):
        """Test that registry methods return consistent results"""
        config = {"tools_includelist": ["contextmanager", "replacetext"]}

        # build_registry should return consistent results
        registry = ToolRegistry.build_registry(config)
        filtered_names = ToolRegistry.get_registered_tools()

        assert set(registry.keys()) == set(
            filtered_names
        ), "Methods should return consistent results"
        assert len(registry) == len(filtered_names), "Methods should return consistent counts"

    def test_skill_tool_detection(self):
        """Test that skill tools are correctly identified"""
        # Get the actual tool classes to verify
        loadskill_tool = ToolRegistry.get_tool("loadskill")
        removeskill_tool = ToolRegistry.get_tool("removeskill")

        # These should exist in the registry
        assert loadskill_tool is not None, "loadskill tool should be registered"
        assert removeskill_tool is not None, "removeskill tool should be registered"

        # Verify they have the correct NORM_NAME
        if loadskill_tool:
            assert loadskill_tool.NORM_NAME == "loadskill"
        if removeskill_tool:
            assert removeskill_tool.NORM_NAME == "removeskill"


if __name__ == "__main__":
    # Run tests if executed directly
    import pytest

    pytest.main([__file__, "-v"])
