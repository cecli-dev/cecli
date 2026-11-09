"""Tests for the desktop PTY terminal manager."""

from __future__ import annotations

import asyncio
import os
import unittest

from desktop.terminal import (
    PipeTerminalSession,
    TerminalBuffer,
    TerminalError,
    TerminalManager,
    TerminalSession,
)


class TerminalBufferTests(unittest.TestCase):
    def test_append_and_snapshot_from_offset(self) -> None:
        buffer = TerminalBuffer(limit=1024)
        self.assertEqual(buffer.append(b"hello"), 5)
        seq, data, reset = buffer.snapshot(0)
        self.assertEqual((seq, data, reset), (5, b"hello", False))
        seq, data, reset = buffer.snapshot(2)
        self.assertEqual((seq, data, reset), (5, b"llo", False))

    def test_ring_trim_marks_reset(self) -> None:
        buffer = TerminalBuffer(limit=1024)
        buffer.append(b"x" * 900)
        buffer.append(b"y" * 900)
        seq, data, reset = buffer.snapshot(0)
        self.assertEqual(seq, 1800)
        self.assertLess(len(data), 1800)
        self.assertTrue(reset)


class TerminalManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_manager_refuses_to_start(self) -> None:
        manager = TerminalManager(enabled=False)
        with self.assertRaises(TerminalError):
            manager.get_or_create("s1", os.getcwd())

    async def test_shell_streams_output_and_accepts_input(self) -> None:
        manager = TerminalManager(enabled=True, shell="/bin/sh")
        session = manager.get_or_create("s1", os.getcwd())
        self.assertIsInstance(session, TerminalSession)
        await session.start()
        try:
            session.write(b"echo terminal-ok\n")
            await self._wait_for(session, b"terminal-ok")
            session.resize(120, 40)
            self.assertEqual((session.cols, session.rows), (120, 40))
        finally:
            await manager.close("s1")
        self.assertIsNone(manager.get("s1"))

    async def test_pipe_backend_streams_and_accepts_input(self) -> None:
        manager = TerminalManager(enabled=True, shell="/bin/sh", backend="pipe")
        session = manager.get_or_create("pipe", os.getcwd())
        self.assertIsInstance(session, PipeTerminalSession)
        await session.start()
        try:
            await session.write_async(b"echo pipe-ok\n")
            await self._wait_for(session, b"pipe-ok")
        finally:
            await manager.close("pipe")
        self.assertIsNone(manager.get("pipe"))

    async def _wait_for(
        self, session: TerminalSession, needle: bytes, timeout: float = 3.0
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if needle in session.buffer.snapshot()[1]:
                return
            await asyncio.sleep(0.05)
        self.fail(f"terminal did not emit {needle!r}")


if __name__ == "__main__":
    unittest.main()
