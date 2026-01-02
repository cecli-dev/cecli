class CommandRegistry:
    """Registry for command discovery and execution."""

    _commands = {}  # name -> BaseCommand class

    @classmethod
    def register(cls, command_class):
        """Register a command class."""
        name = command_class.NORM_NAME
        cls._commands[name] = command_class

    @classmethod
    def get_command(cls, name):
        """Get command class by name."""
        return cls._commands.get(name)

    @classmethod
    def list_commands(cls):
        """List all registered commands."""
        return list(cls._commands.keys())

    @classmethod
    async def execute(cls, name, io, coder, args, **kwargs):
        """Execute a command by name."""
        command_class = cls.get_command(name)
        if not command_class:
            io.tool_error(f"Command not found: {name}")
            return None

        return await command_class.process_command(io, coder, args, **kwargs)

    @classmethod
    def get_command_help(cls, name: str = None) -> str:
        """
        Get help text for a specific command or all commands.

        Args:
            name: Command name (if None, returns help for all commands)

        Returns:
            Help text string
        """
        if name:
            command_class = cls.get_command(name)
            if not command_class:
                return f"Command not found: {name}"
            return command_class.get_help()
        else:
            help_text = "Available Commands:\n\n"
            for cmd_name in sorted(cls._commands.keys()):
                command_class = cls._commands[cmd_name]
                help_text += f"/{cmd_name}: {command_class.DESCRIPTION}\n"
            return help_text
