import pytest

from cecli.commands.utils.base_command import BaseCommand


class TestCommandMeta:
    """Tests for the CommandMeta metaclass validation."""

    def test_valid_custom_command_is_accepted(self):
        """Test that a valid custom command class is accepted."""

        class CustomCommand(BaseCommand):
            NORM_NAME = "custom"
            DESCRIPTION = "A valid custom command"

            @classmethod
            async def execute(cls, io, coder, args, **kwargs):
                pass

        # If we get here without exception, the test passes
        assert CustomCommand.NORM_NAME == "custom"
        assert CustomCommand.DESCRIPTION == "A valid custom command"

    def test_class_name_must_end_with_command(self):
        """Test that class name must end with 'Command'."""
        with pytest.raises(TypeError, match="Command class must end with 'Command'"):

            class Custom(BaseCommand):
                NORM_NAME = "custom"
                DESCRIPTION = "An invalid custom command"

                @classmethod
                async def execute(cls, io, coder, args, **kwargs):
                    pass

    def test_must_define_norm_name(self):
        """Test that NORM_NAME must be defined."""
        with pytest.raises(TypeError, match="Command class must define NORM_NAME"):

            class CustomCommand(BaseCommand):
                DESCRIPTION = "Missing NORM_NAME"

                @classmethod
                async def execute(cls, io, coder, args, **kwargs):
                    pass

    def test_must_define_description(self):
        """Test that DESCRIPTION must be defined."""
        with pytest.raises(TypeError, match="Command class must define DESCRIPTION"):

            class CustomCommand(BaseCommand):
                NORM_NAME = "custom"

                @classmethod
                async def execute(cls, io, coder, args, **kwargs):
                    pass

    def test_must_implement_execute_method(self):
        """Test that execute method must be implemented."""
        with pytest.raises(TypeError, match="Command class must implement execute method"):

            class CustomCommand(BaseCommand):
                NORM_NAME = "custom"
                DESCRIPTION = "Missing execute method"
