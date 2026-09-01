"""Unit tests for cecli/helpers/server/signals.py — Blinker signal definitions."""

from __future__ import annotations

from cecli.helpers.server import signals


class TestSignalDefinitions:
    """Verify all expected signals are defined and have correct names."""

    EXPECTED_SIGNALS = {
        # Output signals
        "tool_output": "tool-output",
        "tool_call": "tool-call",
        "tool_result": "tool-result",
        "stream_chunk": "stream-chunk",
        "start_response": "start-response",
        "end_response": "end-response",
        "spinner": "spinner",
        "start_task": "start-task",
        "cost_update": "cost-update",
        "error": "error",
        # Input signals
        "ready_for_input": "ready-for-input",
        "user_input": "user-input",
        "confirmation": "confirmation",
    }

    def test_all_signals_exist(self):
        """All expected signal names are defined in the signals module."""
        for name in self.EXPECTED_SIGNALS:
            assert hasattr(signals, name), f"Missing signal: {name}"

    def test_signal_names(self):
        """Each signal has the expected blinker signal name."""
        for attr_name, expected_name in self.EXPECTED_SIGNALS.items():
            sig = getattr(signals, attr_name)
            assert (
                sig.name == expected_name
            ), f"Signal '{attr_name}' has name '{sig.name}', expected '{expected_name}'"


class TestSignalSendReceive:
    """Test that blinker signals can be sent and received."""

    def test_tool_output_send_receive(self):
        """tool_output signal can be sent and received with expected kwargs."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.tool_output.connect(handler)
        signals.tool_output.send(self, text="hello", msg_type="output", coder_uuid="coder-1")
        assert received.get("text") == "hello"
        assert received.get("msg_type") == "output"
        assert received.get("coder_uuid") == "coder-1"

    def test_tool_call_send_receive(self):
        """tool_call signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.tool_call.connect(handler)
        signals.tool_call.send(self, lines=["line1", "line2"], coder_uuid="coder-1")
        assert received.get("lines") == ["line1", "line2"]

    def test_tool_result_send_receive(self):
        """tool_result signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.tool_result.connect(handler)
        signals.tool_result.send(self, text="result", coder_uuid="coder-1")
        assert received.get("text") == "result"

    def test_stream_chunk_send_receive(self):
        """stream_chunk signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.stream_chunk.connect(handler)
        signals.stream_chunk.send(self, text="chunk", coder_uuid="coder-1")
        assert received.get("text") == "chunk"

    def test_start_response_send_receive(self):
        """start_response signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.start_response.connect(handler)
        signals.start_response.send(self, coder_uuid="coder-1")
        assert received.get("coder_uuid") == "coder-1"

    def test_end_response_send_receive(self):
        """end_response signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.end_response.connect(handler)
        signals.end_response.send(self, coder_uuid="coder-1")
        assert received.get("coder_uuid") == "coder-1"

    def test_spinner_send_receive(self):
        """spinner signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.spinner.connect(handler)
        signals.spinner.send(self, action="start", text="loading", coder_uuid="coder-1")
        assert received.get("action") == "start"
        assert received.get("text") == "loading"

    def test_start_task_send_receive(self):
        """start_task signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.start_task.connect(handler)
        signals.start_task.send(
            self, task_id="task-1", title="My Task", task_type="general", coder_uuid="coder-1"
        )
        assert received.get("task_id") == "task-1"
        assert received.get("title") == "My Task"
        assert received.get("task_type") == "general"

    def test_cost_update_send_receive(self):
        """cost_update signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.cost_update.connect(handler)
        signals.cost_update.send(self, cost=0.05, coder_uuid="coder-1")
        assert received.get("cost") == 0.05

    def test_error_send_receive(self):
        """error signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.error.connect(handler)
        signals.error.send(self, message="Something broke", coder_uuid="coder-1")
        assert received.get("message") == "Something broke"

    def test_ready_for_input_send_receive(self):
        """ready_for_input signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.ready_for_input.connect(handler)
        signals.ready_for_input.send(
            self,
            files=["file1.py"],
            commands=["/help"],
            chat_files={"rel_fnames": []},
            coder_uuid="coder-1",
        )
        assert received.get("files") == ["file1.py"]
        assert received.get("commands") == ["/help"]

    def test_user_input_send_receive(self):
        """user_input signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.user_input.connect(handler)
        signals.user_input.send(self, text="my message", coder_uuid="coder-1")
        assert received.get("text") == "my message"

    def test_confirmation_send_receive(self):
        """confirmation signal can be sent and received."""
        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.confirmation.connect(handler)
        signals.confirmation.send(
            self, question="Are you sure?", response=True, coder_uuid="coder-1"
        )
        assert received.get("question") == "Are you sure?"
        assert received.get("response") is True

    def test_multiple_receivers(self):
        """Multiple subscribers can receive the same signal."""
        results = []

        def handler1(sender, **kw):
            results.append("handler1")

        def handler2(sender, **kw):
            results.append("handler2")

        signals.tool_output.connect(handler1)
        signals.tool_output.connect(handler2)
        signals.tool_output.send(self, text="test", coder_uuid="coder-1")
        assert "handler1" in results
        assert "handler2" in results

    def test_disconnect(self):
        """Disconnecting a receiver stops it from receiving signals."""
        results = []

        def handler(sender, **kw):
            results.append("got it")

        signals.tool_output.connect(handler)
        signals.tool_output.send(self, text="first", coder_uuid="coder-1")
        assert len(results) == 1

        signals.tool_output.disconnect(handler)
        signals.tool_output.send(self, text="second", coder_uuid="coder-1")
        assert len(results) == 1  # No additional calls
