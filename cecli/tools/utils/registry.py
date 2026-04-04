"""
Registry for tool discovery and management.

Similar to the command registry in cecli/commands/utils/registry.py,
this provides centralized tool registration, discovery, and filtering
based on agent configuration.
"""

import traceback
from pathlib import Path
from typing import Dict, List, Optional, Set, Type

from cecli.helpers import plugin_manager
from cecli.tools import TOOL_MODULES


class ToolRegistry:
    """Registry for tool discovery and management."""

    _tools: Dict[str, Type] = {}  # normalized name -> Tool class
    _essential_tools: Set[str] = {"contextmanager", "replacetext", "finished"}
    _registry: Dict[str, Type] = {}  # cached filtered registry
    loaded_custom_tools: List[str] = []

    @classmethod
    def register(cls, tool_class):
        """Register a tool class using the name from its SCHEMA."""
        name = None
        if hasattr(tool_class, "SCHEMA"):
            try:
                name = tool_class.SCHEMA.get("function", {}).get("name", "").lower()
            except Exception:
                pass

        if not name and hasattr(tool_class, "NORM_NAME"):
            name = tool_class.NORM_NAME

        if not name:
            # Unable to determine a name, can't register
            return

        cls._tools[name] = tool_class

    @classmethod
    def get_tool(cls, name: str) -> Optional[Type]:
        """Get tool class by normalized name."""
        return cls._tools.get(name, None)

    @classmethod
    def list_tools(cls) -> List[str]:
        """List all registered tool names."""
        return list(cls._tools.keys())

    @classmethod
    def build_registry(cls, agent_config: Optional[Dict] = None) -> Dict[str, Type]:
        """
        Build a filtered registry of tools based on agent configuration.

        Args:
            agent_config: Agent configuration dictionary with optional
                         tools_includelist/tools_excludelist keys

        Returns:
            A dictionary mapping normalized tool names to tool classes.
            Custom loaded tools are stored in `ToolRegistry.loaded_custom_tools`.
        """
        if agent_config is None:
            agent_config = {}

        # Load tools from tool_paths if specified
        tools_paths = agent_config.get("tools_paths", agent_config.get("tool_paths", []))
        loaded_custom_tools = []

        for tool_path in tools_paths:
            path = Path(tool_path)
            if path.is_dir():
                # Find all Python files in the directory
                for py_file in path.glob("*.py"):
                    try:
                        # Load the module using plugin_manager
                        module = plugin_manager.load_module(str(py_file))
                        # Check if module has a Tool class
                        if hasattr(module, "Tool"):
                            cls.register(module.Tool)
                            if module.Tool.NORM_NAME:
                                loaded_custom_tools.append(module.Tool.NORM_NAME)
                    except Exception as e:
                        # Log error but continue with other files
                        print(f"Error loading tool from {py_file}: {e}")
                        print(traceback.format_exc())
            else:
                # If it's a file, try to load it directly
                if path.exists() and path.suffix == ".py":
                    try:
                        module = plugin_manager.load_module(str(path))
                        if hasattr(module, "Tool"):
                            cls.register(module.Tool)
                            if module.Tool.NORM_NAME:
                                loaded_custom_tools.append(module.Tool.NORM_NAME)
                    except Exception as e:
                        print(f"Error loading tool from {path}: {e}")
                        print(traceback.format_exc())

        # Get include/exclude lists from config
        tools_includelist = agent_config.get(
            "tools_includelist", agent_config.get("tools_whitelist", [])
        )
        tools_excludelist = agent_config.get(
            "tools_excludelist", agent_config.get("tools_blacklist", [])
        )

        # Start with a base set of tools
        if tools_includelist:
            # If includelist is provided, start with only those tools
            working_set = set(tools_includelist)
        else:
            # Otherwise, start with all registered tools
            working_set = set(cls._tools.keys())

        # Add essential tools, they can't be removed by the excludelist
        working_set.update(cls._essential_tools)

        # Remove tools from the excludelist, but keep essential ones
        if tools_excludelist:
            for tool_name in tools_excludelist:
                if tool_name in working_set and tool_name not in cls._essential_tools:
                    working_set.remove(tool_name)

        # Build the final registry from the working set
        registry = {name: cls._tools[name] for name in working_set if name in cls._tools}

        # Store the built registry in the class attribute
        cls._registry = registry
        cls.loaded_custom_tools = loaded_custom_tools
        return registry

    @classmethod
    def get_registered_tools(cls) -> List[str]:
        """
        Get the list of registered tools from the cached registry.

        Returns:
            List of normalized tool names that are currently registered

        Raises:
            RuntimeError: If no tools are registered (registry is empty)
        """
        if not cls._registry:
            raise RuntimeError(
                "No tools are currently registered in the registry. "
                "Call build_registry() first to initialize the registry."
            )
        return list(cls._registry.keys())

    @classmethod
    def initialize_registry(cls):
        """Initialize the registry by importing and registering all tools."""
        # Clear existing registry
        cls._tools.clear()

        # Register all tools from TOOL_MODULES
        for module in TOOL_MODULES:
            if hasattr(module, "Tool"):
                tool_class = module.Tool
                cls.register(tool_class)


# Initialize the registry when module is imported
ToolRegistry.initialize_registry()
