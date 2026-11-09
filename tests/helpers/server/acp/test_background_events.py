"""Tests for the ordered ACP background event emitter."""

import base64
import time

from cecli.helpers.server.acp.agent.background_events import BackgroundEventEmitter


def _make_emitter(max_queue=64):
    sent = []
    emitter = BackgroundEventEmitter(sent.append, max_queue=max_queue)
    return emitter, sent


def test_publish_output_coalesces_per_key():
    emitter, sent = _make_emitter()
    emitter.publish_output("bg_1", 3, b"abc")
    emitter.publish_output("bg_1", 6, b"def")

    assert sent == []
    emitter.close()

    output = [p["params"] for p in sent if p["params"]["event"] == "output"]
    assert len(output) == 1
    assert output[0]["key"] == "bg_1"
    assert output[0]["seq"] == 6
    assert base64.b64decode(output[0]["data"]) == b"abcdef"
    assert sent[0]["method"] == "cecli/background/event"
    assert sent[0]["jsonrpc"] == "2.0"


def test_output_is_sent_before_later_event():
    emitter, sent = _make_emitter()
    emitter.publish_output("bg_1", 2, b"hi")
    emitter.publish({"schemaVersion": 1, "event": "exited", "key": "bg_1", "code": 0})
    emitter.close()

    events = [p["params"]["event"] for p in sent]
    assert events.index("output") < events.index("exited")
    assert [p["params"] for p in sent if p["params"]["event"] == "output"][0]["seq"] == 2


def test_seq_is_monotonic_and_not_retroactively_split():
    emitter, sent = _make_emitter()
    emitter.publish_output("bg_1", 4, b"aaaa")
    emitter.publish_output("bg_1", 9, b"bbbbb")
    emitter.close()

    output = [p["params"] for p in sent if p["params"]["event"] == "output"]
    assert len(output) == 1
    assert output[0]["seq"] == 9


def test_large_output_flushes_before_close():
    emitter, sent = _make_emitter()
    emitter.publish_output("bg_1", 16384, b"x" * 16384)

    deadline = time.time() + 1.0
    while not sent and time.time() < deadline:
        time.sleep(0.01)
    emitter.close()

    output = [p["params"] for p in sent if p["params"]["event"] == "output"]
    assert len(output) == 1
    assert output[0]["seq"] == 16384


def test_publish_after_close_is_noop():
    emitter, sent = _make_emitter()
    emitter.close()
    emitter.publish_output("bg_1", 1, b"late")
    emitter.publish({"schemaVersion": 1, "event": "state", "key": "bg_1"})
    time.sleep(0.02)
    assert sent == []
