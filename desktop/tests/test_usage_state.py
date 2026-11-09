#!/usr/bin/env python3
"""Focused checks for the usage payload behind the desktop metrics menu."""

from __future__ import annotations

import sys
import unittest
import weakref
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cecli.helpers.server.acp.agent.agent import AcpAgent  # noqa: E402


class _Model:
    name = "deepseek/deepseek-chat"
    info = {
        "max_input_tokens": 200000,
        "input_cost_per_token": 1e-7,
    }

    def token_count(self, messages):
        return 1234


class _UnpricedModel(_Model):
    info = {"max_input_tokens": 4096}


class _Coder:
    total_cost = 0.0123
    total_tokens_sent = 120
    total_tokens_received = 30
    total_cached_tokens = 90

    @classmethod
    def _get_token_usage_stats(cls, model):
        return (10, 5, 2)

    def get_active_model(self):
        return _Model()


class _LegacyCoder(_Coder):
    total_cost = 0.0
    main_model = _UnpricedModel()

    def get_active_model(self):
        raise AttributeError("not available")


class _IdleCoder(_Coder):
    total_tokens_sent = 0
    total_tokens_received = 0
    total_cached_tokens = 0


class _BrokenCostCoder(_Coder):
    @property
    def total_cost(self):
        raise RuntimeError("boom")


def _usage_for(coder):
    agent = AcpAgent(transport=object())
    agent._coder_ref = weakref.ref(coder)
    agent._context_messages = lambda _coder: []
    return agent._usage_state()


class UsageStateTests(unittest.TestCase):
    def test_reports_tokens_cost_stats_and_cache_ratio(self):
        usage = _usage_for(_Coder())

        self.assertEqual(usage["model"], "deepseek/deepseek-chat")
        self.assertEqual(usage["tokens_sent"], 120)
        self.assertEqual(usage["tokens_received"], 30)
        self.assertEqual(usage["tokens_cached"], 90)
        self.assertAlmostEqual(usage["cache_hit_ratio"], 0.75)
        self.assertAlmostEqual(usage["cost"], 0.0123)
        self.assertEqual(usage["context_size"], 200000)
        self.assertEqual(usage["stats"]["requests_per_minute"], 2)

    def test_falls_back_to_main_model_and_hides_unpriced_cost(self):
        usage = _usage_for(_LegacyCoder())

        self.assertEqual(usage["model"], "deepseek/deepseek-chat")
        self.assertIsNone(usage["cost"])
        self.assertEqual(usage["tokens_sent"], 120)

    def test_one_broken_field_does_not_blank_the_payload(self):
        usage = _usage_for(_BrokenCostCoder())

        self.assertIsNone(usage["cost"])
        self.assertEqual(usage["tokens_sent"], 120)
        self.assertEqual(usage["tokens_cached"], 90)

    def test_state_snapshot_includes_usage(self):
        coder = _Coder()
        agent = AcpAgent(transport=object())
        agent._coder_ref = weakref.ref(coder)
        agent._context_messages = lambda _coder: []
        agent._subagent_state = lambda _coder: []
        agent._context_state = lambda _coder: []
        agent._skills_state = lambda _coder: []
        agent._mcp_state = lambda _coder: []
        agent._workflow_state = lambda _coder: []

        snapshot = agent._state_snapshot(coder)

        self.assertEqual(snapshot["usage"]["tokens_sent"], 120)
        self.assertAlmostEqual(snapshot["usage"]["cache_hit_ratio"], 0.75)

    def test_cache_ratio_is_null_without_sent_tokens(self):
        usage = _usage_for(_IdleCoder())

        self.assertIsNone(usage["cache_hit_ratio"])


if __name__ == "__main__":
    unittest.main()
