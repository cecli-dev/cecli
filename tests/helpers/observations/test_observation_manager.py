from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.helpers.observations.manager import ObservationManager


@pytest.mark.asyncio
async def test_observation_manager_initialization():
    coder = MagicMock()
    coder.uuid = "test-uuid"
    coder.context_compaction_max_tokens = 60000

    manager = ObservationManager.get_instance(coder)
    assert manager.observation_threshold == 20000
    assert manager.reflection_threshold == 40000
    assert manager.observations == []


@pytest.mark.asyncio
async def test_observation_manager_reset():
    coder = MagicMock()
    coder.uuid = "test-uuid-reset"
    coder.context_compaction_max_tokens = 60000
    manager = ObservationManager.get_instance(coder)

    manager.observations = ["obs1"]
    manager._last_observed_index = 5

    manager.reset()
    assert manager.observations == []
    assert manager._last_observed_index == 0


@pytest.mark.asyncio
async def test_check_and_trigger_observation(monkeypatch):
    coder = MagicMock()
    coder.uuid = "test-uuid-trigger"
    coder.context_compaction_max_tokens = 30000
    # threshold = 20000

    mock_manager = MagicMock()
    mock_manager.get_tag_messages.return_value = [{"role": "user", "content": "hello"}] * 100

    with patch(
        "cecli.helpers.observations.manager.ConversationService.get_manager",
        return_value=mock_manager,
    ):
        coder.summarizer.count_tokens.return_value = 25000

        manager = ObservationManager.get_instance(coder)

        with patch.object(manager, "run_observation", new_callable=AsyncMock) as mock_run:
            await manager.check_and_trigger()
            # Should trigger observation because 25000 > 20000
            assert mock_run.called


@pytest.mark.asyncio
async def test_compact_context_with_observations():
    from cecli.coders.base_coder import Coder

    coder = MagicMock(spec=Coder)
    coder.uuid = "test-coder-compaction"
    coder.enable_context_compaction = True
    coder.context_compaction_max_tokens = 1000
    coder.context_compaction_summary_tokens = 100
    coder.last_user_message = "Last user msg"
    coder.io = MagicMock()

    # Mock observation manager with some observations
    obs_manager = ObservationManager.get_instance(coder)
    obs_manager.observations = ["Observation 1"]
    coder.observation_manager = obs_manager

    # Mock prompts
    coder.gpt_prompts = MagicMock()
    coder.gpt_prompts.compaction_prompt = "Compaction Prompt"

    # Mock summarizer
    coder.summarizer = MagicMock()
    # Calls to count_tokens:
    # 1. check_and_trigger: count_tokens(unobserved)
    # 2. check_and_trigger: count_tokens(observations)
    # 3. compact_context_if_needed: done_tokens
    # 4. compact_context_if_needed: cur_tokens
    # 5. compact_context_if_needed: diff_tokens
    # 6. summarize_and_update: count_tokens inside
    coder.summarizer.count_tokens.side_effect = [100, 100, 100, 1000, 0, 50]
    coder.summarizer.summarize_all_as_text = AsyncMock(return_value="Summary Text")

    # Mock manager
    mock_conv_manager = MagicMock()
    cur_messages = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    # 1. check_and_trigger (CUR)
    # 2. compact (DONE)
    # 3. compact (CUR)
    # 4. compact (DIFFS)
    mock_conv_manager.get_messages_dict.side_effect = [cur_messages, [], cur_messages, []]

    with patch(
        "cecli.coders.base_coder.ConversationService.get_manager", return_value=mock_conv_manager
    ):
        # Call the method
        await Coder.compact_context_if_needed(coder, force=True)

        # Verify summarize_all_as_text was called
        assert coder.summarizer.summarize_all_as_text.called

        # Verify observations were prepended to the summary
        expected_content = "HISTORICAL OBSERVATIONS:\nObservation 1\n\nSummary Text"

        # Check that add_message was called with the expected prepended content
        all_calls = mock_conv_manager.add_message.call_args_list
        found = False
        for c in all_calls:
            msg_dict = c[0][0] if c[0] else c[1].get("message_dict")
            if msg_dict and expected_content in msg_dict.get("content", ""):
                found = True
                break
        assert found, "Expected summary with observations not found in add_message calls"


@pytest.mark.asyncio
async def test_compact_context_with_observations_integration():
    from cecli.coders.base_coder import Coder

    coder = MagicMock(spec=Coder)
    coder.uuid = "test-coder-compaction-int"
    coder.enable_context_compaction = True
    coder.context_compaction_max_tokens = 1000
    coder.context_compaction_summary_tokens = 100
    coder.last_user_message = "Last user msg"
    coder.io = MagicMock()

    # Mock observation manager with some observations
    obs_manager = ObservationManager.get_instance(coder)
    obs_manager.observations = ["Observation 1"]
    coder.observation_manager = obs_manager

    # Mock prompts
    coder.gpt_prompts = MagicMock()
    coder.gpt_prompts.compaction_prompt = "Compaction Prompt"

    # Mock summarizer
    coder.summarizer = MagicMock()
    # 1. check_and_trigger: unobserved
    # 2. check_and_trigger: obs
    # 3. compact: done
    # 4. compact: cur
    # 5. compact: diff
    # 6. summarize_and_update: inner
    coder.summarizer.count_tokens.side_effect = [100, 100, 100, 1000, 0, 50]
    coder.summarizer.summarize_all_as_text = AsyncMock(return_value="Summary Text")

    # Mock manager
    mock_conv_manager = MagicMock()
    cur_messages = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    # 1. check_and_trigger (CUR)
    # 2. compact (DONE)
    # 3. compact (CUR)
    # 4. compact (DIFFS)
    mock_conv_manager.get_messages_dict.side_effect = [cur_messages, [], cur_messages, []]

    with patch(
        "cecli.coders.base_coder.ConversationService.get_manager", return_value=mock_conv_manager
    ):
        # Call the method
        await Coder.compact_context_if_needed(coder, force=True)

        # Verify summarize_all_as_text was called
        assert coder.summarizer.summarize_all_as_text.called

        # Verify observations were prepended to the summary
        expected_content = "HISTORICAL OBSERVATIONS:\nObservation 1\n\nSummary Text"

        # Check that add_message was called with the expected prepended content
        all_calls = mock_conv_manager.add_message.call_args_list
        found = False
        for c in all_calls:
            msg_dict = c[0][0] if c[0] else c[1].get("message_dict")
            if msg_dict and expected_content in msg_dict.get("content", ""):
                found = True
                break
        assert found, "Expected summary with observations not found in add_message calls"
