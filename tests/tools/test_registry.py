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
        ToolRegistry._registry.clear()
        ToolRegistry.loaded_custom_tools.clear()
        ToolRegistry.initialize_registry()

    def test_registry_initialization(self):
        """Test that registry is properly initialized"""
        # Registry should have tools after initialization
        tools = ToolRegistry.list_tools()
        assert len(tools) > 0, "Registry should have tools after initialization"

        # Check that essential tools are registered
        essential_tools = {"resourcemanager", "readfile", "yield"}
        for tool in essential_tools:
            assert tool in tools, f"Essential tool {tool} should be registered"

    def test_get_tool(self):
        """Test getting individual tools by name"""
        # Get existing tool
        tool_class = ToolRegistry.get_tool("resourcemanager")
        assert tool_class is not None, "Should get resourcemanager tool"
        assert hasattr(tool_class, "NORM_NAME"), "Tool class should have NORM_NAME"
        assert tool_class.NORM_NAME == "resourcemanager", "Tool name should match"

        # Get non-existent tool
        non_existent = ToolRegistry.get_tool("nonexistenttool")
        assert non_existent is None, "Should return None for non-existent tool"

    def test_build_registry_empty_config(self):
        """Test building registry with empty config"""
        registry = ToolRegistry.build_registry({})

        # Should include all tools (except possibly skill tools)
        assert len(registry) > 0, "Should return tools with empty config"

        # Essential tools should always be included
        assert "resourcemanager" in registry, "Essential tool should be included"
        assert "readfile" in registry, "Essential tool should be included"
        assert "yield" in registry, "Essential tool should be included"

    def test_build_registry_with_includelist(self):
        """Test filtering with tools_includelist"""
        config = {"tools_includelist": ["resourcemanager", "editfile"]}
        registry = ToolRegistry.build_registry(config)

        # Should only include tools from includelist, plus essential tools
        assert len(registry) == 3, "Should include 2 from list + 1 essential"
        assert "resourcemanager" in registry
        assert "editfile" in registry
        assert "yield" in registry  # Essential
        assert "command" not in registry, "Should not include tools not in includelist"

    def test_build_registry_with_excludelist(self):
        """Test filtering with tools_excludelist"""
        config = {"tools_excludelist": ["command", "commandinteractive"]}
        registry = ToolRegistry.build_registry(config)

        # Should exclude specified tools (except essentials)
        assert "command" not in registry, "Should exclude command"
        assert "commandinteractive" not in registry, "Should exclude commandinteractive"
        assert "resourcemanager" in registry, "Essential tool should still be included"

    def test_build_registry_exclude_essential(self):
        """Test that essential tools cannot be excluded"""
        config = {"tools_excludelist": ["resourcemanager", "readfile", "finished", "command"]}
        registry = ToolRegistry.build_registry(config)

        # Essential tools should still be included despite excludelist
        assert "resourcemanager" not in registry, "Non-essential tool can be excluded"
        assert "readfile" not in registry, "Non-essential tool can be excluded"
        assert "yield" in registry, "Essential tool cannot be excluded"
        assert "command" not in registry, "Non-essential tool should be excluded"

    def test_build_registry_combined_filters(self):
        """Test combined filtering with includelist and excludelist"""
        config = {
            "tools_includelist": ["resourcemanager", "editfile", "command"],
            "tools_excludelist": ["commandinteractive"],
        }
        registry = ToolRegistry.build_registry(config)

        # Should respect all filters
        assert len(registry) == 4, "Should include exactly 4 tools (3 from list + yield)"
        assert "resourcemanager" in registry
        assert "editfile" in registry
        assert "yield" in registry
        assert "command" in registry
        assert "commandinteractive" not in registry

    def test_get_filtered_tools(self):
        """Test get_filtered_tools method"""
        config = {"tools_includelist": ["resourcemanager", "editfile"]}
        ToolRegistry.build_registry(config)
        tool_names = ToolRegistry.get_registered_tools()

        # Should return list of tool names
        assert isinstance(tool_names, list)
        # Should include resourcemanager, editfile, and yield (essentials)
        assert len(tool_names) == 3
        assert "resourcemanager" in tool_names
        assert "editfile" in tool_names
        assert "yield" in tool_names  # Essential tool always included

    def test_legacy_config_names(self):
        """Test backward compatibility with legacy config names (whitelist/blacklist)"""
        config = {
            "tools_whitelist": ["resourcemanager", "editfile"],
            "tools_blacklist": ["command"],
        }
        registry = ToolRegistry.build_registry(config)

        # Should work with legacy names
        assert "resourcemanager" in registry
        assert "editfile" in registry
        assert "command" not in registry

    def test_config_precedence(self):
        """Test that new config names take precedence over legacy names"""
        config = {
            "tools_includelist": ["resourcemanager"],
            "tools_whitelist": ["command"],  # Should be ignored
            "tools_excludelist": ["commandinteractive"],
            "tools_blacklist": ["finished"],  # Should be ignored for essential tool
        }
        registry = ToolRegistry.build_registry(config)

        # New names should take precedence
        assert "resourcemanager" in registry, "Should use tools_includelist"
        assert (
            "command" not in registry
        ), "Should not use tools_whitelist when tools_includelist present"
        assert "commandinteractive" not in registry, "Should use tools_excludelist"
        assert "yield" in registry, "Essential tool cannot be excluded"

    def test_registry_consistency(self):
        """Test that registry methods return consistent results"""
        config = {"tools_includelist": ["resourcemanager", "editfile"]}

        # build_registry should return consistent results
        registry = ToolRegistry.build_registry(config)
        filtered_names = ToolRegistry.get_registered_tools()

        assert set(registry.keys()) == set(
            filtered_names
        ), "Methods should return consistent results"
        assert len(registry) == len(filtered_names), "Methods should return consistent counts"

    def test_skill_and_mcp_tools_in_context_manager(self):
        """Test that skill/MCP functionality is now part of context_manager."""
        # The individual load_skill, remove_skill, load_mcp, remove_mcp tools
        # have been merged into context_manager
        ctx_tool = ToolRegistry.get_tool("resourcemanager")
        assert ctx_tool is not None, "resourcemanager tool should be registered"
        assert ctx_tool.NORM_NAME == "resourcemanager"

        # Verify the merged tools no longer exist as separate entries
        assert ToolRegistry.get_tool("loadskill") is None
        assert ToolRegistry.get_tool("removeskill") is None

        # Verify context_manager has the new schema parameters
        params = ctx_tool.SCHEMA["function"]["parameters"]["properties"]
        assert "load_skill" in params, "context_manager should have load_skill param"
        assert "remove_skill" in params, "context_manager should have remove_skill param"
        assert "load_mcp" in params, "context_manager should have load_mcp param"
        assert "remove_mcp" in params, "context_manager should have remove_mcp param"

    def test_build_registry_scans_default_tools_dirs(self, tmp_path):
        """build_registry scans the global and local default tools directories."""
        local_dir = tmp_path / ".cecli" / "tools"
        local_dir.mkdir(parents=True)
        (local_dir / "custom_tool.py").write_text(
            "class Tool:\n"
            "    NORM_NAME = 'custom_tool'\n"
            "    SCHEMA = {'function': {'name': 'custom_tool', 'description': 'desc'}}\n"
        )

        registry = ToolRegistry.build_registry({}, root=str(tmp_path))
        assert "custom_tool" in registry


if __name__ == "__main__":
    # Run tests if executed directly
    import pytest

    pytest.main([__file__, "-v"])
