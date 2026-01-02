import json
import textwrap
from unittest.mock import MagicMock, patch

import litellm

from cecli.coders.base_coder import Coder
from cecli.dump import dump  # noqa
from cecli.io import InputOutput
from cecli.models import Model
from cecli.reasoning_tags import (
    REASONING_END,
    REASONING_START,
    remove_reasoning_content,
)


# Mock classes for streaming response testing
class MockDelta:
    """Mock delta object for streaming responses."""

    def __init__(self, content=None, reasoning_content=None, reasoning=None):
        if content is not None:
            self.content = content
        if reasoning_content is not None:
            self.reasoning_content = reasoning_content
        if reasoning is not None:
            self.reasoning = reasoning


class MockStreamingChunk:
    """Mock streaming chunk object for testing stream responses."""

    def __init__(self, content=None, reasoning_content=None, reasoning=None, finish_reason=None):
        self.choices = [MagicMock()]
        self.choices[0].delta = MockDelta(content, reasoning_content, reasoning)
        self.choices[0].finish_reason = finish_reason
        self._hidden_params = {}


class TestReasoning:
    SYNTHETIC_COMPLETION = textwrap.dedent("""\
        {
          "id": "test-completion",
          "created": 0,
          "model": "synthetic/hf:MiniMaxAI/MiniMax-M2",
          "object": "chat.completion",
          "system_fingerprint": null,
          "choices": [
            {
              "finish_reason": "stop",
              "index": 0,
              "message": {
                "content": "Final synthetic summary of the repository.",
                "role": "assistant",
                "tool_calls": null,
                "function_call": null,
                "reasoning_content": "Internal reasoning about how to describe the repo."
              },
              "token_ids": null
            }
          ],
          "usage": {
            "completion_tokens": 10,
            "prompt_tokens": 5,
            "total_tokens": 15,
            "completion_tokens_details": null,
            "prompt_tokens_details": {
              "audio_tokens": null,
              "cached_tokens": null,
              "text_tokens": null,
              "image_tokens": null
            }
          },
          "prompt_token_ids": null
        }
        """)

    async def test_send_with_reasoning_content(self):
        """Test that reasoning content is properly formatted and output."""
        # Setup IO with no pretty
        io = InputOutput(pretty=False)
        io.assistant_output = MagicMock()

        # Setup model and coder
        model = Model("gpt-3.5-turbo")

        # Create mock args with debug=False to avoid AttributeError
        mock_args = MagicMock()
        mock_args.debug = False

        coder = await Coder.create(model, None, io=io, stream=False, args=mock_args)

        # Test data
        reasoning_content = "My step-by-step reasoning process"
        main_content = "Final answer after reasoning"

        # Create litellm.ModelResponse with reasoning_content
        completion_dict = {
            "id": "test-completion",
            "created": 0,
            "model": "gpt-3.5-turbo",
            "object": "chat.completion",
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {
                        "content": main_content,
                        "role": "assistant",
                        "reasoning_content": reasoning_content,
                    },
                }
            ],
            "usage": {"completion_tokens": 10, "prompt_tokens": 5, "total_tokens": 15},
        }
        completion = litellm.ModelResponse(**completion_dict)

        # Create a mock hash object
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "mock_hash_digest"

        # Mock the model's send_completion method to return the expected tuple format
        with patch.object(model, "send_completion", return_value=(mock_hash, completion)):
            # Call send with a simple message
            messages = [{"role": "user", "content": "test prompt"}]
            [item async for item in coder.send(messages)]

            # Now verify ai_output was called with the right content
            io.assistant_output.assert_called_once()
            output = io.assistant_output.call_args[0][0]

            dump(output)

            # Output should contain formatted reasoning tags
            assert REASONING_START in output
            assert REASONING_END in output

            # Output should include both reasoning and main content
            assert reasoning_content in output
            assert main_content in output

            # Verify that partial_response_content only contains the main content
            coder.remove_reasoning_content()
            assert coder.partial_response_content.strip() == main_content.strip()

            # Ensure proper order: reasoning first, then main content
            reasoning_pos = output.find(reasoning_content)
            main_pos = output.find(main_content)
            assert reasoning_pos < main_pos, "Reasoning content should appear before main content"

    async def test_reasoning_keeps_answer_block(self):
        """Ensure providers returning reasoning+answer still show both sections."""
        io = InputOutput(pretty=False)
        io.assistant_output = MagicMock()
        model = Model("gpt-4o")

        # Create mock args with debug=False to avoid AttributeError
        mock_args = MagicMock()
        mock_args.debug = False

        coder = await Coder.create(model, None, io=io, stream=False, args=mock_args)

        completion = litellm.ModelResponse(**json.loads(self.SYNTHETIC_COMPLETION))
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "hash"

        with patch.object(model, "send_completion", return_value=(mock_hash, completion)):
            [item async for item in coder.send([{"role": "user", "content": "describe"}])]

        output = io.assistant_output.call_args[0][0]
        assert REASONING_START in output
        assert "Internal reasoning about how to describe the repo." in output
        assert "Final synthetic summary of the repository." in output
        assert REASONING_END in output

        coder.remove_reasoning_content()
        assert (
            coder.partial_response_content.strip() == "Final synthetic summary of the repository."
        )

    async def test_send_with_reasoning_content_stream(self):
        """Test that streaming reasoning content is properly formatted and output."""
        # Setup IO with pretty output for streaming
        io = InputOutput(pretty=True)
        mock_mdstream = MagicMock()
        io.get_assistant_mdstream = MagicMock(return_value=mock_mdstream)

        # Setup model and coder
        model = Model("gpt-3.5-turbo")

        # Create mock args with debug=False to avoid AttributeError
        mock_args = MagicMock()
        mock_args.debug = False

        coder = await Coder.create(model, None, io=io, stream=True, args=mock_args)

        # Ensure the coder shows pretty output
        coder.show_pretty = MagicMock(return_value=True)

        # Create chunks to simulate streaming
        chunks = [
            # First chunk with reasoning content starts the tag
            MockStreamingChunk(reasoning_content="My step-by-step "),
            # Additional reasoning content
            MockStreamingChunk(reasoning_content="reasoning process"),
            # Switch to main content - this will automatically end the reasoning tag
            MockStreamingChunk(content="Final "),
            # More main content
            MockStreamingChunk(content="answer "),
            MockStreamingChunk(content="after reasoning"),
            # End the response
            MockStreamingChunk(finish_reason="stop"),
        ]

        # Create async generator from chunks
        async def async_chunks():
            for chunk in chunks:
                yield chunk

        # Create a mock hash object
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "mock_hash_digest"

        # Mock the model's send_completion to return the hash and completion
        with (
            patch.object(model, "send_completion", return_value=(mock_hash, async_chunks())),
            patch.object(model, "token_count", return_value=10),
            patch("litellm.stream_chunk_builder", return_value=None),
        ):  # Mock token count and stream_chunk_builder to avoid serialization issues
            # Set mdstream directly on the coder object
            coder.mdstream = mock_mdstream

            # Call send with a simple message
            messages = [{"role": "user", "content": "test prompt"}]
            [item async for item in coder.send(messages)]

            # Get the formatted response content from the coder
            coder.live_incremental_response(True)

            # The partial response content should contain both reasoning and main content
            final_text = coder.partial_response_content

            # The final text should include both reasoning and main content
            assert "My step-by-step reasoning process" in final_text
            assert "Final answer after reasoning" in final_text

            # Ensure proper order: reasoning first, then main content
            reasoning_pos = final_text.find("My step-by-step reasoning process")
            main_pos = final_text.find("Final answer after reasoning")
            assert reasoning_pos < main_pos, "Reasoning content should appear before main content"

            # Verify that after removing reasoning content, only the main content remains
            coder.remove_reasoning_content()
            expected_content = "Final answer after reasoning"
            assert coder.partial_response_content.strip() == expected_content

    async def test_send_with_think_tags(self):
        """Test that <think> tags are properly processed and formatted."""
        # Setup IO with no pretty
        io = InputOutput(pretty=False)
        io.assistant_output = MagicMock()

        # Setup model and coder
        model = Model("gpt-3.5-turbo")
        model.reasoning_tag = "think"  # Set to remove <think> tags
        coder = await Coder.create(model, None, io=io, stream=False)

        # Test data
        reasoning_content = "My step-by-step reasoning process"
        main_content = "Final answer after reasoning"

        # Create content with think tags
        combined_content = f"""<think>
{reasoning_content}
</think>

{main_content}"""

        # Create litellm.ModelResponse with think tags in content
        completion_dict = {
            "id": "test-completion",
            "created": 0,
            "model": "gpt-3.5-turbo",
            "object": "chat.completion",
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {"content": combined_content, "role": "assistant"},
                }
            ],
            "usage": {"completion_tokens": 10, "prompt_tokens": 5, "total_tokens": 15},
        }
        completion = litellm.ModelResponse(**completion_dict)

        # Create a mock hash object
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "mock_hash_digest"

        # Mock the model's send_completion method to return the expected tuple format
        with patch.object(model, "send_completion", return_value=(mock_hash, completion)):
            # Call send with a simple message
            messages = [{"role": "user", "content": "test prompt"}]
            [item async for item in coder.send(messages)]

            # Now verify ai_output was called with the right content
            io.assistant_output.assert_called_once()
            output = io.assistant_output.call_args[0][0]

            dump(output)

            # Output should contain formatted reasoning tags
            assert REASONING_START in output
            assert REASONING_END in output

            # Output should include both reasoning and main content
            assert reasoning_content in output
            assert main_content in output

            # Ensure proper order: reasoning first, then main content
            reasoning_pos = output.find(reasoning_content)
            main_pos = output.find(main_content)
            assert reasoning_pos < main_pos, "Reasoning content should appear before main content"

            # Verify that partial_response_content only contains the main content
            coder.remove_reasoning_content()
            assert coder.partial_response_content.strip() == main_content.strip()

    async def test_send_with_think_tags_stream(self):
        """Test that streaming with <think> tags is properly processed and formatted."""
        # Setup IO with pretty output for streaming
        io = InputOutput(pretty=True)
        mock_mdstream = MagicMock()
        io.get_assistant_mdstream = MagicMock(return_value=mock_mdstream)

        # Setup model and coder
        model = Model("gpt-3.5-turbo")
        model.reasoning_tag = "think"  # Set to remove <think> tags

        # Create mock args with debug=False to avoid AttributeError
        mock_args = MagicMock()
        mock_args.debug = False

        coder = await Coder.create(model, None, io=io, stream=True, args=mock_args)

        # Ensure the coder shows pretty output
        coder.show_pretty = MagicMock(return_value=True)

        # Create chunks to simulate streaming with think tags
        chunks = [
            # Start with open think tag
            MockStreamingChunk(content="<think>\n", reasoning_content=None),
            # Reasoning content inside think tags
            MockStreamingChunk(content="My step-by-step ", reasoning_content=None),
            MockStreamingChunk(content="reasoning process\n", reasoning_content=None),
            # Close think tag
            MockStreamingChunk(content="</think>\n\n", reasoning_content=None),
            # Main content
            MockStreamingChunk(content="Final ", reasoning_content=None),
            MockStreamingChunk(content="answer ", reasoning_content=None),
            MockStreamingChunk(content="after reasoning", reasoning_content=None),
            # End the response
            MockStreamingChunk(finish_reason="stop"),
        ]

        # Create async generator from chunks
        async def async_chunks():
            for chunk in chunks:
                yield chunk

        # Create a mock hash object
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "mock_hash_digest"

        # Mock the model's send_completion to return the hash and completion
        with (
            patch.object(model, "send_completion", return_value=(mock_hash, async_chunks())),
            patch("litellm.stream_chunk_builder", return_value=None),
        ):
            # Set mdstream directly on the coder object
            coder.mdstream = mock_mdstream

            # Call send with a simple message
            messages = [{"role": "user", "content": "test prompt"}]
            [item async for item in coder.send(messages)]

            # Get the formatted response content from the coder
            coder.live_incremental_response(True)

            # The partial response content should contain the formatted output
            final_text = coder.partial_response_content

            # The final text should include both reasoning and main content
            assert "My step-by-step reasoning process" in final_text
            assert "Final answer after reasoning" in final_text

            # Ensure proper order: reasoning first, then main content
            reasoning_pos = final_text.find("My step-by-step reasoning process")
            main_pos = final_text.find("Final answer after reasoning")
            assert reasoning_pos < main_pos, "Reasoning content should appear before main content"

    def test_remove_reasoning_content(self):
        """Test the remove_reasoning_content function from reasoning_tags module."""
        # Test with no removal configured
        text = "Here is <think>some reasoning</think> and regular text"
        assert remove_reasoning_content(text, None) == text

        # Test with removal configured
        text = """Here is some text
<think>
This is reasoning that should be removed
Over multiple lines
</think>
And more text here"""
        expected = """Here is some text

And more text here"""
        assert remove_reasoning_content(text, "think") == expected

        # Test with multiple reasoning blocks
        text = """Start
<think>Block 1</think>
Middle
<think>Block 2</think>
End"""
        expected = """Start

Middle

End"""
        assert remove_reasoning_content(text, "think") == expected

        # Test with no reasoning blocks
        text = "Just regular text"
        assert remove_reasoning_content(text, "think") == text

    async def test_send_with_reasoning(self):
        """Test that reasoning content from the 'reasoning' attribute is properly formatted
        and output."""
        # Setup IO with no pretty
        io = InputOutput(pretty=False)
        io.assistant_output = MagicMock()

        # Setup model and coder
        model = Model("gpt-3.5-turbo")

        # Create mock args with debug=False to avoid AttributeError
        mock_args = MagicMock()
        mock_args.debug = False

        coder = await Coder.create(model, None, io=io, stream=False, args=mock_args)

        # Test data
        reasoning_content = "My step-by-step reasoning process"
        main_content = "Final answer after reasoning"

        # Create litellm.ModelResponse with reasoning attribute
        completion_dict = {
            "id": "test-completion",
            "created": 0,
            "model": "gpt-3.5-turbo",
            "object": "chat.completion",
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {
                        "content": main_content,
                        "role": "assistant",
                        "reasoning": (
                            reasoning_content  # Using reasoning instead of reasoning_content
                        ),
                    },
                }
            ],
            "usage": {"completion_tokens": 10, "prompt_tokens": 5, "total_tokens": 15},
        }
        completion = litellm.ModelResponse(**completion_dict)

        # Create a mock hash object
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "mock_hash_digest"

        # Mock the model's send_completion method to return the expected tuple format
        with patch.object(model, "send_completion", return_value=(mock_hash, completion)):
            # Call send with a simple message
            messages = [{"role": "user", "content": "test prompt"}]
            [item async for item in coder.send(messages)]

            # Now verify ai_output was called with the right content
            io.assistant_output.assert_called_once()
            output = io.assistant_output.call_args[0][0]

            dump(output)

            # Output should contain formatted reasoning tags
            assert REASONING_START in output
            assert REASONING_END in output

            # Output should include both reasoning and main content
            assert reasoning_content in output
            assert main_content in output

            # Verify that partial_response_content only contains the main content
            coder.remove_reasoning_content()
            assert coder.partial_response_content.strip() == main_content.strip()

            # Ensure proper order: reasoning first, then main content
            reasoning_pos = output.find(reasoning_content)
            main_pos = output.find(main_content)
            assert reasoning_pos < main_pos, "Reasoning content should appear before main content"

    async def test_send_with_reasoning_stream(self):
        """Test that streaming reasoning content from the 'reasoning' attribute is properly
        formatted and output."""
        # Setup IO with pretty output for streaming
        io = InputOutput(pretty=True)
        mock_mdstream = MagicMock()
        io.get_assistant_mdstream = MagicMock(return_value=mock_mdstream)

        # Setup model and coder
        model = Model("gpt-3.5-turbo")

        # Create mock args with debug=False to avoid AttributeError
        mock_args = MagicMock()
        mock_args.debug = False

        coder = await Coder.create(model, None, io=io, stream=True, args=mock_args)

        # Ensure the coder shows pretty output
        coder.show_pretty = MagicMock(return_value=True)

        # Create chunks to simulate streaming - using reasoning attribute instead of
        # reasoning_content
        chunks = [
            # First chunk with reasoning content starts the tag
            MockStreamingChunk(reasoning="My step-by-step "),
            # Additional reasoning content
            MockStreamingChunk(reasoning="reasoning process"),
            # Switch to main content - this will automatically end the reasoning tag
            MockStreamingChunk(content="Final "),
            # More main content
            MockStreamingChunk(content="answer "),
            MockStreamingChunk(content="after reasoning"),
            # End the response
            MockStreamingChunk(finish_reason="stop"),
        ]

        # Create async generator from chunks
        async def async_chunks():
            for chunk in chunks:
                yield chunk

        # Create a mock hash object
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "mock_hash_digest"

        # Mock the model's send_completion to return the hash and completion
        with (
            patch.object(model, "send_completion", return_value=(mock_hash, async_chunks())),
            patch.object(model, "token_count", return_value=10),
            patch("litellm.stream_chunk_builder", return_value=None),
        ):  # Mock token count and stream_chunk_builder to avoid serialization issues
            # Set mdstream directly on the coder object
            coder.mdstream = mock_mdstream

            # Call send with a simple message
            messages = [{"role": "user", "content": "test prompt"}]
            [item async for item in coder.send(messages)]

            # Get the formatted response content from the coder
            coder.live_incremental_response(True)

            # The partial response content should contain both reasoning and main content
            final_text = coder.partial_response_content

            # The final text should include both reasoning and main content
            assert "My step-by-step reasoning process" in final_text
            assert "Final answer after reasoning" in final_text

            # Ensure proper order: reasoning first, then main content
            reasoning_pos = final_text.find("My step-by-step reasoning process")
            main_pos = final_text.find("Final answer after reasoning")
            assert reasoning_pos < main_pos, "Reasoning content should appear before main content"

            # Verify that after removing reasoning content, only the main content remains
            coder.remove_reasoning_content()
            expected_content = "Final answer after reasoning"
            assert coder.partial_response_content.strip() == expected_content

    async def test_simple_send_with_retries_removes_reasoning(self):
        """Test that simple_send_with_retries correctly removes reasoning content."""
        model = Model("deepseek-r1")  # This model has reasoning_tag="think"

        # Mock the completion response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="""Here is some text
<think>
This reasoning should be removed
</think>
And this text should remain"""))]

        messages = [{"role": "user", "content": "test"}]

        # Mock the hash object
        mock_hash = MagicMock()
        mock_hash.hexdigest.return_value = "mock_hash_digest"

        with patch.object(model, "send_completion", return_value=(mock_hash, mock_response)):
            result = await model.simple_send_with_retries(messages)

            expected = """Here is some text

And this text should remain"""
            assert result == expected
