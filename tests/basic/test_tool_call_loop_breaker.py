"""Tests for multi-turn duplicate tool call loop breaker in BaseCoder."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.coders.base_coder import Coder
from cecli.helpers.threading import ThreadSafeEvent


def make_tool_call(name, args, call_id="call-1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(args) if isinstance(args, dict) else str(args),
        ),
    )


def test_normalize_tool_call_sig():
    sig1 = Coder._normalize_tool_call_sig("local--Orchestrate", '{"code": "print(1)"}')
    sig2 = Coder._normalize_tool_call_sig("Orchestrate", '{"code": "print(1)"}')
    sig3 = Coder._normalize_tool_call_sig("orchestrate", '{\n  "code":  "print(1)"\n}')
    assert sig1 == sig2 == sig3 == ("orchestrate", '{"code": "print(1)"}')


@pytest.mark.asyncio
async def test_duplicate_tool_call_intercepted_at_threshold():
    coder = MagicMock(spec=Coder)
    coder.num_tool_calls = 0
    coder.max_tool_calls = 25
    coder.max_consecutive_duplicate_tool_calls = 3
    coder.max_duplicate_tool_loop_abort = 5
    coder._last_tool_signatures = None
    coder._consecutive_duplicate_tool_rounds = 0
    coder.io = MagicMock()
    coder._normalize_tool_call_sig = Coder._normalize_tool_call_sig
    coder.interrupt_event = ThreadSafeEvent()

    tc = make_tool_call("local--Orchestrate", {"code": "print(Path('foo').is_file())"}, "call-1")

    with patch("cecli.helpers.conversation.ConversationService.get_manager") as get_mgr:
        mock_mgr = MagicMock()
        get_mgr.return_value = mock_mgr

        # Bind methods to our mock coder
        coder._extract_and_prepare_tool_calls = MagicMock(return_value=[tc])
        coder._group_tools_by_executor = MagicMock(return_value={})
        coder._tool_calls_need_confirmation = MagicMock(return_value=False)
        coder._print_tool_call_info = MagicMock()
        coder._execute_tool_groups = AsyncMock(return_value={})

        # Round 1 - normal
        await Coder.process_tool_calls(coder, None)
        assert coder._consecutive_duplicate_tool_rounds == 1
        assert coder._execute_tool_groups.call_count == 1

        # Round 2 - normal
        await Coder.process_tool_calls(coder, None)
        assert coder._consecutive_duplicate_tool_rounds == 2
        assert coder._execute_tool_groups.call_count == 2

        # Round 3 - threshold reached, intercepted!
        res = await Coder.process_tool_calls(coder, None)
        assert res is True
        assert coder._consecutive_duplicate_tool_rounds == 3
        # Tool was NOT executed a 3rd time
        assert coder._execute_tool_groups.call_count == 2

        # Error was added to conversation to instruct model to break loop
        assert mock_mgr.add_message.call_count >= 1
        last_msg = mock_mgr.add_message.call_args.kwargs["message_dict"]
        assert last_msg["role"] == "tool"
        assert "Repetitive tool call loop detected" in last_msg["content"]
        assert "local--Orchestrate" in last_msg["content"]


@pytest.mark.asyncio
async def test_duplicate_tool_call_aborts_at_hard_limit():
    coder = MagicMock(spec=Coder)
    coder.num_tool_calls = 0
    coder.max_tool_calls = 25
    coder.max_consecutive_duplicate_tool_calls = 3
    coder.max_duplicate_tool_loop_abort = 5
    coder._last_tool_signatures = None
    coder._consecutive_duplicate_tool_rounds = 4
    coder.io = MagicMock()
    coder._normalize_tool_call_sig = Coder._normalize_tool_call_sig
    coder.interrupt_event = ThreadSafeEvent()
    coder.agent_finished = False

    tc = make_tool_call("local--Orchestrate", {"code": "print(1)"}, "call-1")
    coder._last_tool_signatures = (coder._normalize_tool_call_sig(tc.function.name, tc.function.arguments),)

    with patch("cecli.helpers.conversation.ConversationService.get_manager") as get_mgr:
        coder._extract_and_prepare_tool_calls = MagicMock(return_value=[tc])

        # 5th identical round triggers abort
        res = await Coder.process_tool_calls(coder, None)
        assert res is True
        assert coder.agent_finished is True
        assert coder.reflected_message is None
        coder.io.tool_warning.assert_called()


@pytest.mark.asyncio
async def test_yield_exempt_from_duplicate_detection():
    coder = MagicMock(spec=Coder)
    coder.num_tool_calls = 0
    coder.max_tool_calls = 25
    coder.max_consecutive_duplicate_tool_calls = 3
    coder.max_duplicate_tool_loop_abort = 5
    coder._last_tool_signatures = None
    coder._consecutive_duplicate_tool_rounds = 0
    coder.io = MagicMock()
    coder._normalize_tool_call_sig = Coder._normalize_tool_call_sig
    coder.interrupt_event = ThreadSafeEvent()

    tc = make_tool_call("local--Yield", {"wait": 30}, "call-1")
    coder._extract_and_prepare_tool_calls = MagicMock(return_value=[tc])
    coder._group_tools_by_executor = MagicMock(return_value={})
    coder._tool_calls_need_confirmation = MagicMock(return_value=False)
    coder._print_tool_call_info = MagicMock()
    coder._execute_tool_groups = AsyncMock(return_value={})

    for _ in range(5):
        await Coder.process_tool_calls(coder, None)

    # Consecutive counter should stay 0 for Yield
    assert coder._consecutive_duplicate_tool_rounds == 0
    assert coder._execute_tool_groups.call_count == 5
