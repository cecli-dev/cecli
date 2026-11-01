import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cecli.coders import Coder


class TestCoderSwitching(unittest.TestCase):
    @patch("cecli.coders.agent_coder.ToolRegistry")
    @patch("cecli.mcp.manager.ToolRegistry")
    def test_switch_from_agent_to_non_agent(self, mock_mcp_tool_registry, mock_tool_registry):
        async def run_test():
            # Mock dependencies
            io = MagicMock()
            args = MagicMock()
            args.agent_config = "{}"
            args.verbose = False
            args.tui = False
            args.show_thinking = True
            args.auto_save = False
            args.file_diffs = True
            args.max_reflections = 3
            main_model = MagicMock()
            main_model.edit_format = "diff"
            main_model.agent_model = None
            main_model.weak_model = MagicMock()
            main_model.editor_model = None
            main_model.get_repo_map_tokens.return_value = 1024
            main_model.info = {}
            main_model.name = "test-model"
            main_model.reasoning_tag = "think"
            main_model.get_active_model.return_value = main_model

            mock_tool_registry.get_registered_tools.return_value = ["editfile"]
            mock_tool_registry.get_tool.return_value = MagicMock()
            mock_tool_registry.build_registry.return_value = None

            # 1. Start with an AgentCoder
            agent_coder = await Coder.create(
                main_model=main_model,
                edit_format="agent",
                io=io,
                args=args,
            )
            from cecli.coders import AgentCoder

            self.assertIsInstance(agent_coder, AgentCoder)
            self.assertTrue(agent_coder.mcp_manager.get_server("Local").is_connected)

            # 2. Switch to a non-agent coder
            code_coder = await Coder.create(
                from_coder=agent_coder,
                edit_format="code",
            )
            self.assertNotIsInstance(code_coder, AgentCoder)

            # 3. Check that "Local" server is disconnected
            self.assertFalse(code_coder.mcp_manager.get_server("Local").is_connected)

            # 4. Switch back to agent coder
            new_agent_coder = await Coder.create(
                from_coder=code_coder,
                edit_format="agent",
            )
            self.assertIsInstance(new_agent_coder, AgentCoder)

            # 5. Check that "Local" server is re-connected
            self.assertTrue(new_agent_coder.mcp_manager.get_server("Local").is_connected)

        asyncio.run(run_test())

    @patch("cecli.coders.agent_coder.ToolRegistry")
    @patch("cecli.mcp.manager.ToolRegistry")
    def test_scheduler_hands_off_across_coder_switch(
        self, mock_mcp_tool_registry, mock_tool_registry
    ):
        async def run_test():
            io = MagicMock()
            args = MagicMock()
            args.agent_config = "{}"
            args.verbose = False
            args.tui = False
            args.show_thinking = True
            args.auto_save = False
            args.file_diffs = True
            args.max_reflections = 3
            main_model = MagicMock()
            main_model.edit_format = "diff"
            main_model.agent_model = None
            main_model.weak_model = MagicMock()
            main_model.editor_model = None
            main_model.get_repo_map_tokens.return_value = 1024
            main_model.info = {}
            main_model.name = "test-model"
            main_model.reasoning_tag = "think"
            main_model.get_active_model.return_value = main_model

            mock_tool_registry.get_registered_tools.return_value = ["editfile"]
            mock_tool_registry.get_tool.return_value = MagicMock()
            mock_tool_registry.build_registry.return_value = None

            coder = await Coder.create(
                main_model=main_model,
                edit_format="agent",
                io=io,
                args=args,
            )

            running = SimpleNamespace(running=True, coder=coder)
            coder.scheduler = running

            switched = await Coder.create(from_coder=coder, edit_format="code")

            self.assertIs(switched.scheduler, running)
            self.assertIs(running.coder, switched)
            self.assertIsNone(coder.scheduler)

            # A stopped scheduler (post-reload state) must not be handed on.
            stopped = SimpleNamespace(running=False, coder=switched)
            switched.scheduler = stopped

            restarted = await Coder.create(from_coder=switched, edit_format="agent")
            self.assertFalse(hasattr(restarted, "scheduler"))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
