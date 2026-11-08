#!/usr/bin/env python3
"""Manual smoke check for the real-browser preview bridge.

Launches an installed Chrome/Edge/Chromium with a scratch profile, loads a data
URL, waits for the first JPEG screencast frame, forwards a few input events and
reloads. The browser is always shut down, so nothing stays running.

Usage: python3 desktop/scripts/browser_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from browser_bridge import BrowserBridge  # noqa: E402


async def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cecli-browser-smoke-") as profile:
        bridge = BrowserBridge(profile=profile, port=9351)
        try:
            state = await bridge.start()
            if not state["running"]:
                print(f"browser failed to start: {state['error']}")
                return 1
            print(f"started {state['browser']} ({state['executable']})")

            queue = bridge.subscribe()
            state = await bridge.open(
                "data:text/html,<title>Smoke</title><h1>cecli browser smoke</h1>"
            )
            print(f"opened {state['url']} title={state['title']!r}")

            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    event = await asyncio.wait_for(queue.get(), 1.0)
                except asyncio.TimeoutError:
                    continue
                if event.get("type") == "frame":
                    print(f"frame received: {len(event['data'])} base64 chars")
                    break
            else:
                print("no screencast frame arrived")
                return 1

            await bridge.set_viewport(800, 600, 1.0)
            await bridge.send_input({"kind": "mouse", "type": "mousePressed", "x": 20, "y": 20})
            await bridge.send_input({"kind": "mouse", "type": "mouseReleased", "x": 20, "y": 20})
            await bridge.send_input({"kind": "text", "text": "cecli"})
            await bridge.send_input({"kind": "key", "type": "keyDown", "key": "Enter"})
            await bridge.action("reload")
            print("viewport, input and reload commands accepted")
            bridge.unsubscribe(queue)
        finally:
            await bridge.shutdown()
        print(f"shutdown clean: running={bridge.snapshot()['running']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
