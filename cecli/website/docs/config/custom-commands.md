# Custom Commands

Cecli allows you to create and use custom commands to extend its functionality. Custom commands are Python classes that extend the `BaseCommand` class and can be loaded from specified directories or files.

## How Custom Commands Work

### Command Registry System

Cecli uses a centralized command registry that manages all available commands:

- **Built-in Commands**: Standard commands like `/add`, `/model`, `/help`, etc.
- **Custom Commands**: User-defined commands loaded from specified paths
- **Command Discovery**: Automatic loading of commands from configured directories

### Configuration

Custom commands can be configured using the `command-paths` configuration option in your YAML configuration file:

```yaml
custom:
    command-paths: [".cecli/custom/commands", "~/my-commands/", "./special_command.py"]
```

The `command-paths` configuration option allows you to specify directories or files containing custom commands to load.

The `command-paths` can include:
- **Directories**: All `.py` files in the directory will be scanned for `CustomCommand` classes
- **Individual Python files**: Specific command files can be loaded directly

When cecli starts, it:
1. **Parses configuration**: Reads `command-paths` from config files
2. **Scans directories**: Looks for Python files in specified directories
3. **Loads modules**: Imports each Python file as a module
4. **Registers commands**: Finds classes named `CustomCommand` and registers them
5. **Makes available**: Registered commands appear in `/help` and can be executed

### Creating Custom Commands

Custom commands are created by writing Python files that follow this structure:

```python
from typing import List
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result

class CustomCommand(BaseCommand):
    NORM_NAME = "custom-command"
    DESCRIPTION = "Description of what the command does"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """
        Execute the custom command.

        Args:
            io: InputOutput instance
            coder: Coder instance (may be None for some commands)
            args: Command arguments as string
            **kwargs: Additional context

        Returns:
            Optional result (most commands return None)
        """
        # Command implementation here
        result = f"Command executed with arguments: {args}"
        return format_command_result(io, cls.NORM_NAME, result)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """
        Get completion options for this command.

        Args:
            io: InputOutput instance
            coder: Coder instance
            args: Partial arguments for completion

        Returns:
            List of completion strings
        """
        # Return completion options or raise CommandCompletionException
        # for dynamic completions
        return []

    @classmethod
    def get_help(cls) -> str:
        """
        Get help text for this command.

        Returns:
            String containing help text for the command
        """
        help_text = super().get_help()
        help_text += "\nAdditional information about this custom command."
        return help_text
```

### Important Requirements

1. **Class Name**: The command class **must** be named exactly `CustomCommand`
2. **Inheritance**: Must inherit from `BaseCommand` (from `cecli.commands.utils.base_command`)
3. **Class Properties**: Must define `NORM_NAME` and `DESCRIPTION` class attributes
4. **Execute Method**: Must implement the `execute` class method

### Example: Add List Command

Here's a complete example of a custom command that adds a list of numbers:

```python
from typing import List
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result

class CustomCommand(BaseCommand):
    NORM_NAME = "add-list"
    DESCRIPTION = "Add a list of numbers."

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the context command with given parameters."""
        num_list = map(int, filter(None, args.split(" ")))
        return format_command_result(io, cls.NORM_NAME, sum(num_list))

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for context command."""
        # The original completions_context raises CommandCompletionException
        # This is handled by the completion system
        from cecli.io import CommandCompletionException
        raise CommandCompletionException()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the context command."""
        help_text = super().get_help()
        help_text += "Add list of integers"
        return help_text
```

#### Complete Configuration Example

Complete configuration example in YAML configuration file (`.cecli.conf.yml` or `~/.cecli.conf.yml`):

```yaml
# Model configuration
model: gemini/gemini-3-pro-preview
weak-model: gemini/gemini-3-flash-preview

# Custom commands configuration
custom:
    command-paths: [".cecli/custom/commands"]

# Other cecli options
...
```

### Error Handling

If there are errors loading custom commands:

- **Invalid paths**: Warnings are logged but cecli continues to run
- **Syntax errors**: The specific file fails to load but other commands still work
- **Missing requirements**: Commands that can't be imported are skipped

### Best Practices

1. **Organize commands**: Group related commands in the same directory
2. **Use descriptive names**: Make `NORM_NAME` clear, memorable, and unique
3. **Provide good help**: Implement `get_help()` with clear usage instructions
4. **Handle errors gracefully**: Use `format_command_result()` for consistent output
5. **Test commands**: Verify commands work before adding to production config

### Integration with Other Features

Custom commands work seamlessly with other cecli features:

- **Command completion**: Custom commands appear in tab completion
- **Help system**: Included in `/help` output
- **TUI interface**: Available in the graphical interface
- **Agent Mode**: Can be used alongside Agent Mode tools

### Benefits

- **Extensibility**: Add project-specific functionality
- **Automation**: Create commands for repetitive tasks
- **Integration**: Connect cecli with other tools and systems
- **Customization**: Tailor cecli to your specific workflow

Custom commands provide a powerful way to extend cecli's capabilities, allowing you to create specialized functionality for your specific needs while maintaining the familiar command interface.