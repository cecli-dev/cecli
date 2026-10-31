class CommandRegistry:
    """Registry for command discovery and execution."""

    _commands = {}  # name -> BaseCommand class
    _aliases = {}  # alias name -> (command name, subcommand)

    @classmethod
    def register(cls, command_class):
        """Register a command class and its aliases."""
        name = command_class.NORM_NAME
        cls._commands[name] = command_class

        subcommands = getattr(command_class, "SUBCOMMANDS", ())
        for alias, subcommand in getattr(command_class, "ALIASES", {}).items():
            if subcommand not in subcommands:
                raise ValueError(
                    f"Alias '{alias}' for '{name}' routes to unknown subcommand '{subcommand}'"
                )

            cls._aliases[alias] = (name, subcommand)

    @classmethod
    def resolve_alias(cls, name):
        """Return ``(command name, subcommand)`` for an alias, or None."""
        return cls._aliases.get(name)

    @classmethod
    def get_command(cls, name):
        """Get command class by name, resolving aliases to their target."""
        alias = cls._aliases.get(name)
        if alias:
            name = alias[0]

        return cls._commands.get(name)

    @classmethod
    def list_commands(cls, include_aliases=False):
        """List registered command names, optionally including aliases."""
        names = list(cls._commands.keys())
        if include_aliases:
            names.extend(cls._aliases.keys())

        return names

    @classmethod
    async def execute(cls, name, io, coder, args, **kwargs):
        """Execute a command by name, expanding aliases to their subcommand."""
        alias = cls.resolve_alias(name)
        if alias:
            name, subcommand = alias
            args = f"{subcommand} {args}".strip()

        command_class = cls.get_command(name)
        if not command_class:
            io.tool_error(f"Command not found: {name}")
            return None

        return await command_class.process_command(io, coder, args, **kwargs)

    @classmethod
    def get_command_description(cls, name: str, subcommand: str = "") -> str:
        """
        Get description for a specific command or one of its subcommands.

        Args:
            name: Command name
            subcommand: Optional subcommand name

        Returns:
            Usage hint for the subcommand when one is registered, otherwise the
            command description, or an empty string if the command is not found
        """
        alias = cls.resolve_alias(name)
        if alias:
            name, subcommand = alias

        command_class = cls.get_command(name)
        if not command_class:
            return ""

        if subcommand:
            usage = getattr(command_class, "SUBCOMMAND_USAGE", {})
            if subcommand in usage:
                return usage[subcommand]

        return command_class.DESCRIPTION or ""

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
