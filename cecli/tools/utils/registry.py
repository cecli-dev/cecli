"""
Registry for tool discovery and management.

Similar to the command registry in cecli/commands/utils/registry.py,
this provides centralized tool registration, discovery, and filtering
based on agent configuration.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Type

from cecli.helpers import plugin_manager
from cecli.tools import TOOL_MODULES


class ToolRegistry:
    """Registry for tool discovery and management."""

    _tools: Dict[str, Type] = {}  # normalized name -> Tool class
    _essential_tools: Set[str] = {"contextmanager", "replacetext", "finished"}
    _registry: Dict[str, Type] = {}  # cached filtered registry

    @classmethod
    def register(cls, tool_class):
        """Register a tool class."""
        name = tool_class.NORM_NAME
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
    def build_registry(cls, agent_config: Optional[Dict] = None, **kwargs) -> Dict[str, Type]:
        """
        Build a filtered registry of tools based on agent configuration.

        Args:
            agent_config: Agent configuration dictionary with optional
                         tools_includelist/tools_excludelist keys

        Returns:
            Dictionary mapping normalized tool names to tool classes
        """
        if agent_config is None:
            agent_config = {}

        cls.initialize_registry()

        # Load tools from tool_paths if specified
        tool_paths = agent_config.get("tool_paths", [])

        for tool_path in tool_paths:
            path = Path(tool_path)
            if path.is_dir():
                for py_file in path.glob("*.py"):
                    try:
                        module = plugin_manager.load_module(str(py_file))
                        if hasattr(module, "Tool"):
                            cls.register(module.Tool)
                    except Exception as e:
                        print(f"Error loading tool from {py_file}: {e}")
            else:
                if path.exists() and path.suffix == ".py":
                    try:
                        module = plugin_manager.load_module(str(path))
                        if hasattr(module, "Tool"):
                            cls.register(module.Tool)
                    except Exception as e:
                        print(f"Error loading tool from {path}: {e}")

        # Get include/exclude lists from config
        tools_includelist = agent_config.get(
            "tools_includelist", agent_config.get("tools_whitelist", [])
        )
        tools_excludelist = agent_config.get(
            "tools_excludelist", agent_config.get("tools_blacklist", [])
        )

        registry = {}

        for tool_name, tool_class in cls._tools.items():
            should_include = True

            if tools_includelist:
                should_include = tool_name in tools_includelist

            if tool_name in cls._essential_tools:
                should_include = True

            if tool_name in tools_excludelist and tool_name not in cls._essential_tools:
                should_include = False

            if should_include:
                registry[tool_name] = tool_class

        cls._registry = registry
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
        cls._tools.clear()

        for module in TOOL_MODULES:
            if hasattr(module, "Tool"):
                cls.register(module.Tool)


# Initialize the registry when module is imported
ToolRegistry.initialize_registry()
