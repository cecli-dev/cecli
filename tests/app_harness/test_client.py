"""Tests for discovery, authentication, and response parsing."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import client as client_module  # noqa: E402
from cecli.helpers.app_harness.client import (  # noqa: E402
    AppClient,
    AppHarnessError,
    BridgeUnavailable,
    VersionMismatch,
    discover_bridge_file,
    load_bridge_file,
)
from cecli.helpers.app_harness.models import Element  # noqa: E402
from tests.app_harness.conftest import DIALOG_WINDOW  # noqa: E402


def test_discovery_honors_cecli_bridge_file(fake_bridge, tmp_path):
    path = discover_bridge_file()

    assert path == fake_bridge.bridge_path

    bridge = load_bridge_file()

    assert bridge.port == fake_bridge.port
    assert bridge.host == "127.0.0.1"
    assert bridge.token == fake_bridge.token
    assert bridge.mode == "bridge"
    assert bridge.path == fake_bridge.bridge_path


def test_token_header_is_sent(fake_bridge):
    client = AppClient()
    windows = client.windows()

    assert [window.title for window in windows] == ["Excel - Book1"]
    assert fake_bridge.requests[0]["token"] == fake_bridge.token


def test_bad_token_is_rejected(fake_bridge):
    fake_bridge.token = "cd" * 32
    client = AppClient()

    with pytest.raises(AppHarnessError) as info:
        client.windows()

    assert info.value.kind == "unauthorized"


def test_version_mismatch(fake_bridge):
    fake_bridge.write_bridge("9.9.9")

    with pytest.raises(VersionMismatch):
        load_bridge_file()


def test_version_check_can_be_skipped(fake_bridge, monkeypatch):
    fake_bridge.write_bridge("9.9.9")
    monkeypatch.setenv("CECLI_BRIDGE_VERSION_SKIP", "1")

    bridge = load_bridge_file()

    assert bridge.version == "9.9.9"


def test_missing_bridge_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))

    with pytest.raises(BridgeUnavailable):
        load_bridge_file()


def test_state_parsing(fake_bridge):
    state = AppClient().state()

    assert state.platform == "linux"
    assert state.backend == "fake"
    assert state.health == "ready"
    assert state.capabilities == ["windows", "snapshot", "actions"]
    assert state.pid == 4242
    assert state.protocol_version == "0.1.0"


def test_windows_parsing(fake_bridge):
    windows = AppClient().windows()

    assert len(windows) == 1
    window = windows[0]
    assert window.handle == "0x1234"
    assert window.pid == 4242
    assert window.process_id == 4242
    assert window.foreground is True
    assert window.bounds is not None
    assert window.bounds.width == 800


def test_snapshot_parsing_and_truncation(fake_bridge):
    snapshot = AppClient().snapshot("Excel", max_depth=5, max_elements=10)

    assert snapshot.truncated is True
    assert snapshot.total_elements == 99
    assert snapshot.max_depth == 5
    assert len(snapshot.elements) == 4

    save = snapshot.find(name="Save")
    assert save is not None
    assert save.id == 2
    assert save.control_type == "Button"
    assert save.role == "Button"
    assert save.patterns == ["Invoke"]

    password = snapshot.find(name="Password")
    assert password is not None
    assert password.sensitive is True
    assert password.value is None
    assert password.enabled is False
    assert password.offscreen is True
    assert password.parent == 1

    assert fake_bridge.requests[-1]["body"] == {
        "window": "Excel",
        "max_depth": 5,
        "max_elements": 10,
    }


def test_action_payload_and_parsing(fake_bridge):
    result = AppClient().invoke("Excel", {"name": "Save"})

    assert result.action == "invoke"
    assert result.delivered is True
    assert result.verified is True
    assert result.uncertain is False
    assert fake_bridge.action_requests[0] == {
        "window": "Excel",
        "action": "invoke",
        "target": {"name": "Save"},
        "args": {
            "value": None,
            "keys": None,
            "point": None,
            "direction": None,
            "amount": None,
            "extra": {},
        },
    }


def test_get_value_returns_value(fake_bridge):
    result = AppClient().get_value("Excel", {"automation_id": "A1"})

    assert result.value == "hello"


def test_set_value_sends_value(fake_bridge):
    AppClient().set_value("Excel", "1 Main St", {"name": "Address"})

    assert fake_bridge.action_requests[0]["args"]["value"] == "1 Main St"


def test_activate_raises_the_window(fake_bridge):
    AppClient().activate("Excel")

    body = fake_bridge.action_requests[0]
    assert body["window"] == "Excel"
    assert body["action"] == "activate"


def test_scroll_sends_direction_and_amount(fake_bridge):
    AppClient().scroll("Excel", "down", 3)

    body = fake_bridge.action_requests[0]
    assert body["args"]["direction"] == "down"
    assert body["args"]["amount"] == 3


def test_scroll_to_sends_percentages(fake_bridge):
    AppClient().scroll_to("Excel", vertical_percent=50)

    body = fake_bridge.action_requests[0]
    assert body["action"] == "scroll_to"
    assert body["args"]["vertical_percent"] == 50
    assert body["args"].get("horizontal_percent") is None


def test_screenshot_returns_bytes(fake_bridge):
    data = AppClient().screenshot("Excel")

    assert data.startswith(b"\x89PNG")
    assert len(data) > 8


def test_doctor_parsing(fake_bridge):
    report = AppClient().doctor()

    assert report.permissions == {"accessibility": "granted"}
    assert [check.name for check in report.checks] == ["loopback", "token", "screen_capture"]
    assert report.checks[2].ok is False
    assert report.notes == ["fixture bridge"]


def test_backend_error_is_unwrapped(fake_bridge):
    fake_bridge.action_mode = "refuse"

    with pytest.raises(AppHarnessError) as info:
        AppClient().invoke("Excel", {"name": "Save"})

    assert info.value.kind == "input_blocked"
    assert "disabled" in info.value.message


def test_envelope_tolerates_missing_fields(fake_bridge):
    state = client_module.StateInfo.from_dict({"platform": "windows"})

    assert state.platform == "windows"
    assert state.health == "unavailable"


def test_bridge_file_is_not_started_without_ensure(monkeypatch, tmp_path):
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("CECLI_CE_UNDERSCORE", "/nonexistent/ce-underscore")

    with pytest.raises(BridgeUnavailable):
        AppClient()


def test_stale_port_reports_unavailable(fake_bridge):
    payload = json.loads(fake_bridge.bridge_path.read_text(encoding="utf-8"))
    payload["port"] = 1
    fake_bridge.bridge_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BridgeUnavailable):
        AppClient().state()


def test_snapshot_actionable_is_sent_only_when_set(fake_bridge):
    AppClient().snapshot("Excel", actionable=True)

    snapshots = [
        request for request in fake_bridge.requests if request["path"] == "/api/app/snapshot"
    ]

    assert snapshots[-1]["body"]["actionable"] is True


def test_snapshot_omits_actionable_by_default(fake_bridge):
    AppClient().snapshot("Excel")

    snapshots = [
        request for request in fake_bridge.requests if request["path"] == "/api/app/snapshot"
    ]

    assert "actionable" not in snapshots[-1]["body"]


def test_error_details_are_parsed(fake_bridge):
    fake_bridge.find_miss_error = True

    with pytest.raises(AppHarnessError) as info:
        AppClient().find_elements("Excel", "Button[name='Nope']")

    assert info.value.kind == "target_not_found"
    assert info.value.details == {
        "candidates": ['Button "Save" (id2)', 'Button "Save As"'],
        "scope": "window",
    }


def test_target_for_includes_path_when_present():
    element = Element(id=7, runtime_id="42.7", path="Frame/Panel/Button[Save]")

    assert client_module._target_for(element) == {
        "id": 7,
        "runtime_id": "42.7",
        "path": "Frame/Panel/Button[Save]",
    }


def test_target_for_omits_empty_path():
    element = Element(id=7, runtime_id="42.7")

    assert client_module._target_for(element) == {"id": 7, "runtime_id": "42.7"}


def test_error_details_are_absent_by_default(fake_bridge):
    fake_bridge.action_mode = "refuse"

    with pytest.raises(AppHarnessError) as info:
        AppClient().invoke("Excel", {"name": "Save"})

    assert info.value.details is None


def test_snapshot_carries_the_bridge_notes(fake_bridge):
    fake_bridge.snapshot_notes = ["snapshot cut by max_elements (kept 4)"]

    snapshot = AppClient().snapshot("Excel")

    assert snapshot.notes == ["snapshot cut by max_elements (kept 4)"]


def test_snapshot_notes_are_empty_without_a_note(fake_bridge):
    assert AppClient().snapshot("Excel").notes == []


def test_action_outcome_is_parsed_and_serialised(fake_bridge):
    fake_bridge.action_outcome = "pointer"

    result = AppClient().invoke("Excel", {"name": "Save"})

    assert result.outcome == "pointer"
    assert result.to_dict()["outcome"] == "pointer"


def test_action_without_an_outcome_stays_none(fake_bridge):
    assert AppClient().invoke("Excel", {"name": "Save"}).outcome is None


def test_locator_all_returns_every_match(fake_bridge):
    locator = AppClient().locator("Excel", "Edit")

    assert [element.name for element in locator.all()] == ["Address", "Password"]


def test_locator_cell_scopes_the_grid(fake_bridge):
    client = AppClient()

    client.locator("Excel", "Button[name='Save']").cell(4, 2)

    request = fake_bridge.action_requests[-1]

    assert request["action"] == "cell_at"
    assert request["args"]["row"] == 4
    assert request["args"]["column"] == 2
    assert request["target"] == {"id": 2, "runtime_id": "42.3"}


def test_cell_at_without_a_grid_sends_no_target(fake_bridge):
    AppClient().cell_at("Excel", 4, 2)

    assert fake_bridge.action_requests[-1]["target"] is None


def test_snapshot_binds_elements_to_the_client(fake_bridge):
    snapshot = AppClient().snapshot("Excel")
    save = snapshot.find(name="Save")

    assert save is not None

    result = save.click()

    assert result.delivered is True
    assert fake_bridge.action_requests[-1]["target"] == {
        "id": 2,
        "runtime_id": "42.3",
        "automation_id": "SaveButton",
        "name": "Save",
        "role": "Button",
    }


def test_find_binds_returned_elements(fake_bridge):
    matches, _, _ = AppClient().find_elements("Excel", "Button")

    assert len(matches) == 1
    assert matches[0].click().delivered is True
    assert fake_bridge.action_requests[-1]["target"]["id"] == 2


def test_click_point_sends_button_and_count(fake_bridge):
    AppClient().click_point("Excel", (10, 20), button="right", count=2)

    args = fake_bridge.action_requests[-1]["args"]

    assert args["point"] == {"x": 10, "y": 20}
    assert args["button"] == "right"
    assert args["count"] == 2


def test_double_click_resolves_the_target_center(fake_bridge):
    AppClient().double_click("Excel", {"name": "Save"})

    request = fake_bridge.action_requests[-1]

    assert request["action"] == "double_click"
    assert request["args"]["point"] == {"x": 340, "y": 32}


def test_type_text_prefers_set_value(fake_bridge):
    result = AppClient().type_text("Excel", "hello", {"name": "Address"})

    actions = [request["action"] for request in fake_bridge.action_requests]

    assert result.verified is True
    assert actions == ["set_value", "get_value"]


def test_type_text_falls_back_to_keys(fake_bridge):
    fake_bridge.set_value_mode = "unsupported"

    AppClient().type_text("Excel", "hello", {"name": "Address"})

    actions = [request["action"] for request in fake_bridge.action_requests]

    assert actions == ["set_value", "focus", "keys", "keys", "get_value"]
    assert fake_bridge.action_requests[2]["args"]["keys"] == "^a"
    assert fake_bridge.action_requests[3]["args"]["keys"] == "hello"


def test_type_text_uses_the_clipboard_for_unsafe_text(fake_bridge, monkeypatch):
    fake_bridge.set_value_mode = "unsupported"
    copied: list[str] = []
    monkeypatch.setattr(client_module.clipboard, "set_text", copied.append)

    AppClient().type_text("Excel", "bad\x07text", {"name": "Address"})

    assert copied == ["bad\x07text"]
    assert fake_bridge.action_requests[3]["args"]["keys"] == "^v"


def test_literal_key_encoder_braces_special_characters():
    assert client_module.encode_literal_keys("a^b!") == "a{^}b{!}"
    assert client_module.encode_literal_keys("x\ny") == "x{ENTER}y"
    assert client_module.encode_literal_keys("bad\x07") is None


def test_dialogs_prefers_the_endpoint(fake_bridge):
    fake_bridge.dialogs = [DIALOG_WINDOW]

    dialogs = AppClient().dialogs()

    assert [dialog.title for dialog in dialogs] == ["Microsoft Excel"]
    assert dialogs[0].dialog is True
    assert "/api/app/dialogs" in fake_bridge.paths()


def test_dialogs_falls_back_to_windows(fake_bridge):
    fake_bridge.dialogs = [DIALOG_WINDOW]
    fake_bridge.dialogs_route = False
    fake_bridge.include_dialog_in_windows = True

    dialogs = AppClient().dialogs()

    assert [dialog.handle for dialog in dialogs] == ["0x9001"]
    assert "/api/app/windows" in fake_bridge.paths()


def test_input_blocked_mentions_blocking_dialogs(fake_bridge):
    fake_bridge.action_mode = "refuse"
    fake_bridge.dialogs = [DIALOG_WINDOW]

    with pytest.raises(AppHarnessError) as info:
        AppClient().invoke("Excel", {"name": "Save"})

    assert "Microsoft Excel" in info.value.message
    assert info.value.details["dialogs"] == ["Microsoft Excel"]


def test_accept_dialog_uses_the_dialog_window(fake_bridge):
    fake_bridge.dialogs = [DIALOG_WINDOW]

    result = AppClient().accept_dialog(button="OK")

    assert result.delivered is True
    assert fake_bridge.action_requests[-1]["window"] == "0x9001"


def test_dismiss_dialogs_cancels_each_dialog(fake_bridge):
    fake_bridge.dialogs = [DIALOG_WINDOW]

    results = AppClient().dismiss_dialogs()

    assert len(results) == 1
    assert fake_bridge.action_requests[-1]["window"] == "0x9001"


def test_edit_text_replaces_through_type_text(fake_bridge):
    fake_bridge.set_value_mode = "unsupported"

    result = AppClient().edit_text("Excel", "hello", {"name": "Address"})

    assert result.delivered is True
    keys = [request["args"].get("keys") for request in fake_bridge.action_requests]
    assert "^a" in keys
    assert "hello" in keys


def test_click_accepts_button_and_count(fake_bridge):
    AppClient().click("Excel", {"name": "Save"}, button="right", count=2)

    args = fake_bridge.action_requests[-1]["args"]
    assert args["button"] == "right"
    assert args["count"] == 2


def test_expected_bridge_version_matches_cargo_workspace():
    cargo = Path(__file__).resolve().parents[2] / "Cargo.toml"

    if not cargo.exists():
        pytest.skip("Cargo workspace is not present")

    match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        cargo.read_text(encoding="utf-8"),
        re.MULTILINE,
    )

    assert match is not None
    assert client_module.EXPECTED_BRIDGE_VERSION == match.group(1)
