import json
import pytest
from unittest.mock import AsyncMock, call, patch

from cecli.models import _parse_retry_config, Model
from cecli.exceptions import LiteLLMExceptions
from cecli.llm import litellm


def test_parse_retry_config_string():
    config_str = '{"retry_timeout": 15, "retry-on-empty": true}'
    result = _parse_retry_config(config_str)
    assert result["retry_timeout"] == 15.0
    assert result["retry_on_empty"] is True
    # defaults
    assert result["retry_backoff_factor"] == 1.5
    assert result["retry_on_unavailable"] is True


def test_parse_retry_config_dict():
    config_dict = {"retry_timeout": 10.0, "retry_backoff_factor": 2.0, "retry-on-unavailable": False}
    result = _parse_retry_config(config_dict)
    assert result["retry_timeout"] == 10.0
    assert result["retry_backoff_factor"] == 2.0
    assert result["retry_on_unavailable"] is False
    assert result["retry_on_empty"] is False


@pytest.mark.asyncio
async def test_simple_send_with_retries_honors_timeout():
    # Setup model with a short retry timeout limit
    model = Model("gpt-4o", retries={"retry_timeout": 0.5, "retry_backoff_factor": 2.0})

    # retry_delay starts at 0.125 and is multiplied by the backoff factor
    # BEFORE each retry sleep; retry_timeout caps the per-retry delay:
    # attempt 1 fails -> 0.125 * 2.0 = 0.25 (<= 0.5, sleep and retry)
    # attempt 2 fails -> 0.25 * 2.0 = 0.50 (<= 0.5, sleep and retry)
    # attempt 3 fails -> 0.50 * 2.0 = 1.00 (> 0.5, give up)
    # We mock send_completion to continually raise a retryable LiteLLM exception.
    err = litellm.APIConnectionError(
        message="Simulated connection error",
        llm_provider="openai",
        model="gpt-4o",
        request=None
    )
    
    mock_send = AsyncMock(side_effect=err)
    
    with patch.object(model, 'send_completion', mock_send), \
         patch('time.sleep') as mock_sleep, \
         patch('builtins.print'):  # Mute prints in test output
        
        content, response = await model.simple_send_with_retries(messages=[])
        
        # It should exit yielding None, None because it exhausted retries.
        assert content is None
        assert response is None
        
        # The backoff factor is applied before each sleep, so the sleeps are
        # 0.25 then 0.50; the third failure would need 1.0 > 0.5, so it stops.
        
        assert mock_send.call_count == 3
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list == [call(0.25), call(0.5)]
