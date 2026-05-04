"""Tests for base hook classes."""

import pytest

from cecli.hooks import BaseHook, CommandHook, HookType


class MockHook(BaseHook):
    """Mock hook for unit testing."""

    type = HookType.START

    async def execute(self, coder, metadata):
        """Test execution."""
        return True


class MockHookWithReturn(BaseHook):
    """Mock hook that returns a specific value."""

    type = HookType.PRE_TOOL

    def __init__(self, return_value=True, **kwargs):
        super().__init__(**kwargs)
        self.return_value = return_value

    async def execute(self, coder, metadata):
        """Return the configured value."""
        return self.return_value


class MockHookWithException(BaseHook):
    """Mock hook that raises an exception."""

    type = HookType.START

    async def execute(self, coder, metadata):
        """Raise an exception."""
        raise ValueError("Test exception")


class TestBaseHook:
    """Test BaseHook class."""

    def test_hook_creation(self):
        """Test basic hook creation."""
        hook = MockHook(name="test_hook", priority=5, enabled=True)

        assert hook.name == "test_hook"
        assert hook.priority == 5
        assert hook.enabled is True
        assert hook.type == HookType.START

    def test_hook_default_name(self):
        """Test hook uses class name as default."""
        hook = MockHook()
        assert hook.name == "MockHook"

    def test_hook_validation(self):
        """Test hook type validation."""

        class InvalidHook(BaseHook):
            # Missing type attribute
            pass

            async def execute(self, coder, metadata):
                return True

        with pytest.raises(ValueError, match="must define a 'type' attribute"):
            InvalidHook()

    def test_hook_repr(self):
        """Test hook string representation."""
        hook = MockHook(name="test_hook", priority=10, enabled=False)
        repr_str = repr(hook)

        assert "MockHook" in repr_str
        assert "name='test_hook'" in repr_str
        assert "type=HookType.START" in repr_str or "type=START" in repr_str
        assert "priority=10" in repr_str
        assert "enabled=False" in repr_str

    @pytest.mark.asyncio
    async def test_hook_execution(self):
        """Test hook execution."""
        hook = MockHook()
        result = await hook.execute(None, {})

        assert result is True

    @pytest.mark.asyncio
    async def test_hook_with_return_value(self):
        """Test hook with specific return value."""
        hook = MockHookWithReturn(return_value=False)
        result = await hook.execute(None, {})

        assert result is False

    @pytest.mark.asyncio
    async def test_hook_with_exception(self):
        """Test hook that raises exception."""
        hook = MockHookWithException()

        with pytest.raises(ValueError, match="Test exception"):
            await hook.execute(None, {})


class TestCommandHook:
    """Test CommandHook class."""

    def test_command_hook_creation(self):
        """Test command hook creation."""
        hook = CommandHook(
            command="echo test",
            hook_type=HookType.START,
            name="test_command",
            priority=5,
            enabled=True,
        )

        assert hook.name == "test_command"
        assert hook.command == "echo test"
        assert hook.type == HookType.START
        assert hook.priority == 5
        assert hook.enabled is True

    def test_command_hook_defaults(self):
        """Test command hook with defaults."""
        hook = CommandHook(command="echo test", hook_type=HookType.START)
        hook.type = HookType.END

        assert hook.name == "CommandHook"  # Default class name
        assert hook.command == "echo test"
        assert hook.type == HookType.END
        assert hook.priority == 10  # Default priority
        assert hook.enabled is True  # Default enabled

    @pytest.mark.asyncio
    async def test_command_hook_execution(self, mocker):
        """Test command hook execution."""
        # Mock run_cmd to avoid actually running commands
        mock_run_cmd = mocker.patch("cecli.hooks.base.run_cmd")
        mock_run_cmd.return_value = (0, "test output")

        # Mock coder object
        mock_coder = mocker.Mock()
        mock_coder.io = mocker.Mock()
        mock_coder.io.tool_error = mocker.Mock()
        mock_coder.root = "/tmp"
        mock_coder.verbose = False

        hook = CommandHook(command="echo {test_var}", hook_type=HookType.START)

        metadata = {"test_var": "hello"}
        result = await hook.execute(mock_coder, metadata)

        # Check that command was formatted with metadata
        mock_run_cmd.assert_called_once()
        call_args = mock_run_cmd.call_args[0][0]
        assert "echo hello" in call_args

        assert result == 0  # Return code

    @pytest.mark.asyncio
    async def test_command_hook_timeout(self, mocker):
        """Test command hook timeout."""
        import subprocess

        # Mock run_cmd to raise TimeoutExpired
        mock_run_cmd = mocker.patch("cecli.hooks.base.run_cmd")
        mock_run_cmd.side_effect = subprocess.TimeoutExpired("echo test", 30)

        # Mock coder object
        mock_coder = mocker.Mock()
        mock_coder.io = mocker.Mock()
        mock_coder.io.tool_error = mocker.Mock()
        mock_coder.root = "/tmp"
        mock_coder.verbose = False

        hook = CommandHook(command="echo test", hook_type=HookType.START)

        result = await hook.execute(mock_coder, {})

        assert result == 1  # Non-zero exit code on timeout

    @pytest.mark.asyncio
    async def test_command_hook_exception(self, mocker):
        """Test command hook with general exception."""
        # Mock run_cmd to raise general exception
        mock_run_cmd = mocker.patch("cecli.hooks.base.run_cmd")
        mock_run_cmd.side_effect = Exception("Test error")

        # Mock coder object
        mock_coder = mocker.Mock()
        mock_coder.io = mocker.Mock()
        mock_coder.io.tool_error = mocker.Mock()
        mock_coder.root = "/tmp"
        mock_coder.verbose = False

        hook = CommandHook(command="echo test", hook_type=HookType.START)

        result = await hook.execute(mock_coder, {})

        assert result == 1  # Non-zero exit code on exception
