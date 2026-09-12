"""Unit tests for the token-per-minute rate limiter in base_coder.UsageMeta."""

import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def reset_usage():
    """Reset the shared UsageMeta token-usage buffer before each test."""
    from cecli.coders.base_coder import UsageMeta

    UsageMeta._reset_token_usage()
    UsageMeta._total_tokens_sent = 0
    yield UsageMeta


def _dummy(model="model-a", limit=2000000):
    model_obj = SimpleNamespace(name=model)
    return SimpleNamespace(
        args=SimpleNamespace(tokens_per_minute=limit),
        get_active_model=lambda: model_obj,
    )


def test_buffer_records_and_reports_per_model(reset_usage):
    UsageMeta = reset_usage
    now = time.time()

    assert UsageMeta._get_token_usage_stats("model-a") == (0, 0, 0)

    UsageMeta._record_token_usage("model-a", 1000, now=now)
    UsageMeta._record_token_usage("model-a", 500, now=now)
    # A different model is isolated.
    UsageMeta._record_token_usage("model-b", 777, now=now)

    tokens_last_min, max_request, rpm = UsageMeta._get_token_usage_stats("model-a")
    assert tokens_last_min == 1500
    assert max_request == 1000
    assert rpm == 2

    tokens_last_min_b, _, rpm_b = UsageMeta._get_token_usage_stats("model-b")
    assert tokens_last_min_b == 777
    assert rpm_b == 1


def test_buffer_purges_old_entries_per_model(reset_usage):
    UsageMeta = reset_usage
    now = time.time()

    UsageMeta._record_token_usage("model-a", 1000, now=now)
    UsageMeta._record_token_usage("model-a", 999, now=now - 61.0)  # stale

    tokens_last_min, _, rpm = UsageMeta._get_token_usage_stats("model-a")
    assert tokens_last_min == 1000
    assert rpm == 1


def test_buffer_reset_all_and_single_model(reset_usage):
    UsageMeta = reset_usage
    now = time.time()
    UsageMeta._record_token_usage("model-a", 1000, now=now)
    UsageMeta._record_token_usage("model-b", 777, now=now)

    UsageMeta._reset_token_usage("model-a")
    assert UsageMeta._get_token_usage_stats("model-a") == (0, 0, 0)
    assert UsageMeta._get_token_usage_stats("model-b")[0] == 777

    UsageMeta._reset_token_usage()
    assert UsageMeta._get_token_usage_stats("model-b") == (0, 0, 0)


def test_dynamic_sleep_no_burst(reset_usage):
    from cecli.coders.base_coder import Coder

    UsageMeta = reset_usage
    # One 500k request at 1 rpm stays well under budget -> no sleep.
    UsageMeta._record_token_usage("model-a", 500000, now=time.time())
    assert Coder.calculate_dynamic_sleep(_dummy()) == 0.0


def test_dynamic_sleep_burst_rounds_to_quarter(reset_usage):
    from cecli.coders.base_coder import Coder

    UsageMeta = reset_usage
    now = time.time()
    # 30 requests of 500k tokens in the window -> far over the 1.8M budget.
    for _ in range(30):
        UsageMeta._record_token_usage("model-a", 500000, now=now)

    sleep = Coder.calculate_dynamic_sleep(_dummy())
    assert sleep > 0
    assert abs((sleep / 0.25) - round(sleep / 0.25)) < 1e-6
    assert sleep <= 60.0


def test_dynamic_sleep_isolated_per_model(reset_usage):
    from cecli.coders.base_coder import Coder

    UsageMeta = reset_usage
    now = time.time()
    # Only model-b is saturated; model-a must be unaffected.
    for _ in range(30):
        UsageMeta._record_token_usage("model-b", 500000, now=now)

    assert Coder.calculate_dynamic_sleep(_dummy(model="model-a")) == 0.0
    assert Coder.calculate_dynamic_sleep(_dummy(model="model-b")) > 0.0


def test_dynamic_sleep_disabled_with_zero_limit(reset_usage):
    from cecli.coders.base_coder import Coder

    UsageMeta = reset_usage
    UsageMeta._record_token_usage("model-a", 500000, now=time.time())
    assert Coder.calculate_dynamic_sleep(_dummy(limit=0)) == 0.0


def test_dynamic_sleep_missing_args(reset_usage):
    from cecli.coders.base_coder import Coder

    # UsageMeta = reset_usage
    # No args -> falls back to the default limit; empty buffer -> no sleep.
    coder = SimpleNamespace(args=None, get_active_model=lambda: SimpleNamespace(name="model-a"))
    assert Coder.calculate_dynamic_sleep(coder) == 0.0
