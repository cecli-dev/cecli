"""Spec generation agent (repo map + explore + richness deepen)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from cecli.spec.gen_agent import (
    build_deepen_message_for_workspace,
    build_spec_explore_message,
    spec_gen_agent_enabled,
    spec_gen_richness_gate_enabled,
    wrap_spec_generate_message,
)
from cecli.spec.todos import TodoItem


class TestSpecGenAgent(unittest.TestCase):
    def test_explore_message_is_read_only_agent(self):
        item = TodoItem(id="a", title="Complex Patient")
        msg = build_spec_explore_message(
            prompt="iOS journaling app",
            section="requirements",
            item=item,
        )
        self.assertTrue(msg.startswith("/agent"))
        self.assertIn("Do NOT create", msg)
        self.assertIn("Complex Patient", msg)

    def test_wrap_includes_steering_and_exploration(self):
        with patch(
            "cecli.spec.gen_agent.build_spec_focus_preamble",
            return_value="## Project steering\nUse SwiftUI.\n",
        ):
            out = wrap_spec_generate_message(
                "/tmp/ws",
                "## Requirements\nWrite specs.\n",
                exploration="- `Sources/App.swift` exists\n",
            )
        self.assertIn("Project steering", out)
        self.assertIn("Repository exploration", out)
        self.assertIn("App.swift", out)

    def test_compact_disables_agent_and_richness_gate(self):
        prev = os.environ.get("BV_COMPACT_SPEC_GEN")
        os.environ["BV_COMPACT_SPEC_GEN"] = "1"
        try:
            self.assertFalse(spec_gen_agent_enabled())
            self.assertFalse(spec_gen_richness_gate_enabled())
        finally:
            if prev is None:
                os.environ.pop("BV_COMPACT_SPEC_GEN", None)
            else:
                os.environ["BV_COMPACT_SPEC_GEN"] = prev

    def test_compact_write_timeout_uses_full_turn_budget(self):
        from cecli.spec.gen_agent import spec_gen_write_timeout_s

        prev = os.environ.get("BV_COMPACT_SPEC_GEN")
        os.environ["BV_COMPACT_SPEC_GEN"] = "1"
        try:
            self.assertEqual(spec_gen_write_timeout_s(1800.0), 1740.0)
            self.assertEqual(spec_gen_write_timeout_s(600.0), 540.0)
        finally:
            if prev is None:
                os.environ.pop("BV_COMPACT_SPEC_GEN", None)
            else:
                os.environ["BV_COMPACT_SPEC_GEN"] = prev

    def test_deepen_message_carries_suggestions(self):
        item = TodoItem(
            id="a",
            title="T",
            requirements="### REQ-001\n**WHEN** a\n**THE** system **SHALL** b.\n",
        )
        msg = build_deepen_message_for_workspace(
            workspace="/tmp/ws",
            prompt="Feature X",
            item=item,
            section="requirements",
            suggestions=["requirements: add more acceptance criteria"],
        )
        self.assertIn("Deepen the spec", msg)
        self.assertIn("acceptance criteria", msg)

    def test_run_spec_layer_llm_one_shot_when_agent_disabled(self):
        from cecli.spec.gen_agent import run_spec_layer_llm

        item = TodoItem(id="a", title="T")
        runner = MagicMock()
        runner.apply_spec_gen_route = MagicMock()
        runner.run_one_shot.return_value = (
            "## Requirements\n### REQ-001\n**WHEN** a\n**THE** system **SHALL** b.\n"
        )

        with patch("cecli.spec.gen_agent.spec_gen_agent_enabled", return_value=False):
            with patch("cecli.spec.gen_agent.spec_gen_richness_gate_enabled", return_value=False):
                raw = run_spec_layer_llm(
                    runner,
                    workspace="/tmp/ws",
                    prompt="Build it",
                    item=item,
                    section="requirements",
                    mode="generate",
                    todo_id="a",
                    total_turn_timeout_s=600.0,
                )
        self.assertIn("REQ-001", raw)
        runner.run_one_shot.assert_called_once()

    def test_run_spec_layer_llm_deepens_when_richness_gate_fails(self):
        from cecli.spec.gen_agent import run_spec_layer_llm

        item = TodoItem(id="a", title="T")
        runner = MagicMock()
        runner.apply_spec_gen_route = MagicMock()
        thin = "## Requirements\n### REQ-001\n**WHEN** a\n**THE** system **SHALL** b.\n"
        deep = (
            "## Requirements\n### REQ-001\n**WHEN** a\n**THE** system **SHALL** b.\n"
            "### REQ-002\n**WHEN** c\n**THE** system **SHALL** d.\n"
        )
        runner.run_one_shot.side_effect = [thin, deep]

        with patch("cecli.spec.gen_agent.spec_gen_agent_enabled", return_value=False):
            with patch("cecli.spec.gen_agent.spec_gen_richness_gate_enabled", return_value=True):
                raw = run_spec_layer_llm(
                    runner,
                    workspace="/tmp/ws",
                    prompt="Build it",
                    item=item,
                    section="requirements",
                    mode="generate",
                    todo_id="a",
                    total_turn_timeout_s=600.0,
                )
        self.assertEqual(runner.run_one_shot.call_count, 2)
        self.assertIn("REQ-002", raw)

    def test_run_spec_layer_llm_explore_when_agent_enabled(self):
        from cecli.spec.gen_agent import run_spec_layer_llm

        item = TodoItem(id="a", title="T")
        runner = MagicMock()
        runner.apply_spec_gen_route = MagicMock()
        runner.run_message.return_value = iter(
            [{"type": "done", "assistant_text": "- `src/main.py` exists\n"}]
        )
        runner.run_one_shot.return_value = (
            "## Requirements\n### REQ-001\n**WHEN** a\n**THE** system **SHALL** b.\n"
        )

        with patch("cecli.spec.gen_agent.spec_gen_agent_enabled", return_value=True):
            with patch("cecli.spec.gen_agent.spec_gen_richness_gate_enabled", return_value=False):
                raw = run_spec_layer_llm(
                    runner,
                    workspace="/tmp/ws",
                    prompt="Build it",
                    item=item,
                    section="requirements",
                    mode="generate",
                    todo_id="a",
                    total_turn_timeout_s=600.0,
                )
        runner.run_message.assert_called_once()
        self.assertIn("REQ-001", raw)


if __name__ == "__main__":
    unittest.main()
