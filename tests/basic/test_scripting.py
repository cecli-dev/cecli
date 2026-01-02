from pathlib import Path
from unittest.mock import patch

from cecli.coders import Coder
from cecli.models import Model
from cecli.utils import GitTemporaryDirectory


class TestScriptingAPI:
    @patch("cecli.coders.base_coder.Coder.send")
    async def test_basic_scripting(self, mock_send):
        with GitTemporaryDirectory():
            # Setup - create an async generator mock
            async def mock_send_side_effect(messages, functions=None, tools=None):
                # Simulate the async generator behavior
                coder.partial_response_content = "Changes applied successfully."
                coder.partial_response_function_call = None
                yield "Changes applied successfully."

            mock_send.side_effect = mock_send_side_effect

            # Test script
            fname = Path("greeting.py")
            fname.touch()
            fnames = [str(fname)]
            model = Model("gpt-4-turbo")
            coder = await Coder.create(main_model=model, fnames=fnames)

            result1 = await coder.run("make a script that prints hello world")
            result2 = await coder.run("make it say goodbye")

            # Assertions
            assert mock_send.call_count == 2
            assert result1 == "Changes applied successfully."
            assert result2 == "Changes applied successfully."
