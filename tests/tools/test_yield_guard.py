"""Yield guard on implement turns (reject_yield hook)."""

from __future__ import annotations

import asyncio
import unittest

from cecli.tools._yield import Tool


class _CoderStub:
    def __init__(self, *, reject_message: str | None = None):
        self.reject_yield = (
            (lambda _c, **_k: reject_message) if reject_message is not None else None
        )
        self.agent_finished = False


class TestYieldGuard(unittest.TestCase):
    def test_yield_rejected_when_hook_blocks(self):
        coder = _CoderStub(
            reject_message="Yield rejected: no file edits saved this implement turn."
        )

        result = asyncio.run(Tool.execute(coder, summary="done"))

        self.assertIn("Yield rejected", result)
        self.assertFalse(coder.agent_finished)


if __name__ == "__main__":
    unittest.main()
