import inspect
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from cecli.decoding import safe_open
from cecli.helpers.plugin_manager import load_module

from .base import BaseHook, CommandHook
from .manager import HookManager
from .types import HookType


class HookRegistry:
    """Registry for loading user-defined hooks from files.

    Per-coder instance managed via WeakKeyDictionary + _uuid_index,
    matching the pattern used by HookManager and ConversationManager.
    """

    _instances = weakref.WeakKeyDictionary()  # coder -> HookRegistry
    _uuid_index = weakref.WeakValueDictionary()  # uuid -> HookRegistry

    def __init__(self, coder):
        """Initialize the hook registry.

        Args:
            coder: The coder instance this registry belongs to.
        """
        self.coder = weakref.ref(coder)
        self.uuid = coder.uuid
        self.hook_manager = HookManager.get_instance(coder)
        self.loaded_modules = set()

    @classmethod
    def get_instance(cls, coder) -> "HookRegistry":
        """Get or create a HookRegistry for the given coder.

        Uses the same WeakKeyDictionary + _uuid_index pattern as HookManager.

        Args:
            coder: The coder instance.

        Returns:
            The HookRegistry instance for this coder.
        """
        if coder in cls._instances:
            return cls._instances[coder]
        if coder.uuid in cls._uuid_index:
            instance = cls._uuid_index[coder.uuid]
            if instance.get_coder() is not coder:
                instance.coder = weakref.ref(coder)
            cls._instances[coder] = instance
            return instance
        instance = cls(coder)
        cls._instances[coder] = instance
        cls._uuid_index[coder.uuid] = instance
        return instance

    @classmethod
    def destroy_instance(cls, coder_uuid: str):
        """Remove an instance by UUID.

        Args:
            coder_uuid: The UUID of the coder whose registry should be destroyed.
        """
        instance = cls._uuid_index.pop(coder_uuid, None)
        if instance:
            coder = instance.get_coder()
            if coder is not None:
                cls._instances.pop(coder, None)

    def get_coder(self):
        """Return the coder instance, or None if it has been garbage collected."""
        return self.coder()

    def load_hooks_from_directory(self, directory: Path) -> List[str]:
        """Load hooks from a directory containing Python files.

        Args:
            directory: Path to directory containing hook files.

        Returns:
            List of hook names that were loaded.
        """
        if not directory.exists():
            return []

        loaded_hooks = []

        # Load Python files
        for file_path in directory.glob("*.py"):
            if file_path.name == "__init__.py":
                continue

            hooks = self._load_hooks_from_python_file(file_path)
            loaded_hooks.extend(hooks)

        return loaded_hooks

    def load_hooks_from_config(self, config_file: Path) -> List[str]:
        """Load hooks from a YAML configuration file.

        Args:
            config_file: Path to YAML configuration file.

        Returns:
            List of hook names that were loaded.
        """
        if not config_file.exists():
            return []

        try:
            with safe_open(config_file, "r") as f:
                config = yaml.safe_load(f)
        except (yaml.YAMLError, IOError) as e:
            print(f"Warning: Could not load hook config from {config_file}: {e}")
            return []

        if not config:
            return []

        if "hooks" not in config:
            new_config = {"hooks": config}
            config = new_config

        loaded_hooks = []
        hooks_config = config["hooks"]

        for hook_type_str, hook_defs in hooks_config.items():
            # Validate hook type
            try:
                hook_type = HookType(hook_type_str)
            except ValueError:
                print(f"Warning: Invalid hook type '{hook_type_str}' in config")
                continue

            for hook_def in hook_defs:
                hook = self._create_hook_from_config(hook_def, hook_type)
                if hook:
                    try:
                        self.hook_manager.register_hook(hook)
                        loaded_hooks.append(hook.name)
                    except ValueError as e:
                        # Hook might already be registered (e.g., from _load_hooks_from_python_file)
                        # Still count it as loaded
                        if "already exists" in str(e):
                            loaded_hooks.append(hook.name)
                        else:
                            print(f"Warning: Could not register hook '{hook.name}': {e}")

        return loaded_hooks

    def _load_hooks_from_python_file(self, file_path: Path) -> List[str]:
        """Load hooks from a Python file."""
        try:
            # Load the module using centralized plugin manager
            module = load_module(file_path)

            # Find all BaseHook subclasses in the module
            hooks = []
            for name, obj in inspect.getmembers(module):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BaseHook)
                    and obj != BaseHook
                    and obj != CommandHook
                ):
                    try:
                        # Instantiate the hook
                        hook = obj()
                        self.hook_manager.register_hook(hook)
                        hooks.append(hook.name)
                    except ValueError as e:
                        # Hook might already be registered; still count as loaded
                        if "already exists" in str(e):
                            hooks.append(hook.name)
                        else:
                            print(f"Warning: Could not register hook '{name}': {e}")
                    except Exception as e:
                        print(f"Warning: Could not instantiate hook {name}: {e}")

            # Track loaded module
            self.loaded_modules.add(module.__name__)

            return hooks

        except Exception as e:
            print(f"Warning: Could not load hooks from {file_path}: {e}")
            return []

    def _create_hook_from_config(
        self, hook_def: Dict[str, Any], hook_type: HookType
    ) -> Optional[BaseHook]:
        """Create a hook instance from configuration definition."""
        if not isinstance(hook_def, dict):
            print(f"Warning: Hook definition must be a dictionary, got {type(hook_def)}")
            return None

        # Get hook name
        name = hook_def.get("name")
        if not name:
            print("Warning: Hook definition missing 'name' field")
            return None

        # Get priority, enabled state, and description
        priority = hook_def.get("priority", 10)
        enabled = hook_def.get("enabled", True)
        description = hook_def.get("description")

        # Check if it's a file-based hook or command hook
        if "file" in hook_def:
            # Python file hook
            file_path = Path(hook_def["file"]).expanduser()
            if not file_path.exists():
                print(f"Warning: Hook file not found: {file_path}")
                return None

            # Load the module and find the hook class
            hooks = self._load_hooks_from_python_file(file_path)
            if not hooks:
                print(f"Warning: No hooks found in file: {file_path}")
                return None

            # The hook should have been registered by _load_hooks_from_python_file
            # We need to find it and update its priority/enabled state
            if self.hook_manager.hook_exists(name):
                hook = self.hook_manager._hooks_by_name[name]
                hook.priority = priority
                hook.enabled = enabled
                if description is not None:
                    hook.description = description
                return hook
            else:
                print(f"Warning: Hook '{name}' not found in file {file_path}")
                return None

        elif "command" in hook_def:
            # Command hook
            command = hook_def["command"]
            hook = CommandHook(
                command=command, name=name, priority=priority, enabled=enabled, hook_type=hook_type
            )
            hook.type = hook_type
            if description is not None:
                hook.description = description
            return hook

        else:
            print(f"Warning: Hook '{name}' must have either 'file' or 'command' field")
            return None

    def load_default_hooks(self) -> List[str]:
        """Load hooks from default locations."""
        loaded_hooks = []

        # Load from user's .cecli/hooks directory
        user_hooks_dir = Path.home() / ".cecli" / "hooks"
        if user_hooks_dir.exists():
            hooks = self.load_hooks_from_directory(user_hooks_dir)
            loaded_hooks.extend(hooks)

        # Load from user's .cecli/hooks.yml configuration
        user_config = Path.home() / ".cecli" / "hooks.yml"
        if user_config.exists():
            hooks = self.load_hooks_from_config(user_config)
            loaded_hooks.extend(hooks)

        return loaded_hooks

    def load_hooks_from_json(self, json_string: str) -> List[str]:
        """Load hooks from a JSON string.

        Args:
            json_string: JSON string containing hooks configuration.

        Returns:
            List of hook names that were loaded.
        """
        import json as json_module
        import tempfile

        try:
            # Parse JSON string
            config_data = json_module.loads(json_string)

            # Convert to YAML
            yaml_data = yaml.dump(config_data)

            # Create a temporary file with YAML content
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as temp_file:
                temp_file.write(yaml_data)
                temp_file_path = Path(temp_file.name)

            try:
                # Load hooks from the temporary YAML file
                loaded_hooks = self.load_hooks_from_config(temp_file_path)
            finally:
                # Clean up temporary file
                temp_file_path.unlink(missing_ok=True)

            return loaded_hooks

        except json_module.JSONDecodeError as e:
            print(f"Error: Invalid JSON string for hooks configuration: {e}")
            return []
        except Exception as e:
            print(f"Error loading hooks from JSON: {e}")
            return []

    def reload_hooks(self) -> List[str]:
        """Reload all hooks from default locations."""
        # Clear existing hooks
        self.hook_manager.clear()
        self.loaded_modules.clear()

        # Clear module cache from plugin_manager
        try:
            from cecli.helpers.plugin_manager import module_cache

            module_cache.clear()
        except ImportError:
            pass

        # Load hooks again
        return self.load_default_hooks()
