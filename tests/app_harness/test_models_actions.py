"""Tests for model geometry, element actions and locator ergonomics."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness.client import AppHarnessError  # noqa: E402
from cecli.helpers.app_harness.locator import Locator  # noqa: E402
from cecli.helpers.app_harness.models import (  # noqa: E402
    ActionResult,
    Element,
    Point,
    Rect,
    Snapshot,
    Window,
)


class _StubClient:
    """Record action calls and serve a fixed set of matches."""

    def __init__(self, matches: list[Element] | None = None) -> None:
        self.timeout_ms = 1000
        self.matches = matches or []
        self.calls: list[tuple[str, tuple, dict]] = []

    def refresh(self) -> int:
        return 0

    def find_elements(self, window, selector, limit, max_depth, max_elements, exclude_roles):
        return list(self.matches), len(self.matches), False

    def click(self, window, target=None, point=None):
        self.calls.append(("click", (window, target, point), {}))
        return ActionResult(action="click", delivered=True, verified=True)

    def action(self, window, action, target=None, **args):
        self.calls.append((action, (window, target), args))
        return ActionResult(action=action, delivered=True, verified=True)

    def snapshot(self, *args, **kwargs):
        return None

    def cell_at(self, *args, **kwargs):
        return ActionResult(action="cell_at", delivered=True, verified=True)


def _button(**kwargs) -> Element:
    defaults = {
        "id": 2,
        "control_type": "Button",
        "name": "Save",
        "runtime_id": "42.3",
        "bounds": Rect(300, 20, 80, 24),
    }
    defaults.update(kwargs)
    return Element(**defaults)


def test_point_and_rect_centers():
    rect = Rect(10, 20, 200, 24)

    assert rect.center == Point(110, 32)
    assert rect.center.to_dict() == {"x": 110, "y": 32}


def test_window_dialog_and_center():
    window = Window.from_dict(
        {
            "title": "Alert",
            "bounds": {"left": 0, "top": 0, "width": 800, "height": 600},
            "dialog": True,
        }
    )

    assert window.dialog is True
    assert window.center == Point(400, 300)
    assert Window().center is None


def test_lean_record_exposes_compact_bounds_and_center():
    record = _button().to_dict(lean=True)

    assert record["bounds"] == "300,20,80,24"
    assert record["center"] == "340,32"
    assert _button(bounds=None).to_dict(lean=True)["bounds"] is None
    assert _button(bounds=None).to_dict(lean=True)["center"] is None


def test_binding_does_not_pollute_asdict():
    element = _button().bind(_StubClient(), "Excel")

    serialized = asdict(element)

    assert "_client" not in serialized
    assert "_window" not in serialized


def test_unbound_element_raises_a_clear_error():
    with pytest.raises(AppHarnessError) as info:
        _button().click()

    assert info.value.kind == "invalid_request"
    assert "not bound" in str(info.value)


def test_element_semantic_and_pointer_actions():
    client = _StubClient()
    element = _button().bind(client, "Excel")

    element.click()
    element.click(at="center")
    element.double_click()
    element.right_click()
    element.hover()

    assert client.calls[0][0] == "click"
    assert client.calls[0][1][2] is None
    assert client.calls[1][0] == "click"
    assert client.calls[1][1][2] == {"x": 340, "y": 32}
    assert [call[0] for call in client.calls[2:]] == [
        "double_click",
        "right_click",
        "hover",
    ]
    assert all(call[2]["point"] == {"x": 340, "y": 32} for call in client.calls[2:])


def test_element_semantic_actions_use_the_target():
    client = _StubClient()
    element = _button().bind(client, "Excel")

    element.invoke()
    element.set_value("pressed")
    element.get_value()
    element.focus()
    element.select()
    element.scroll_into_view()

    assert [call[0] for call in client.calls] == [
        "invoke",
        "set_value",
        "get_value",
        "focus",
        "select",
        "scroll_into_view",
    ]
    assert client.calls[1][2]["value"] == "pressed"
    assert all(call[1][1] == element.target() for call in client.calls)


def test_element_text_actions_fall_back_to_the_action_route():
    client = _StubClient()
    element = _button().bind(client, "Excel")

    element.type_text("hello")
    element.edit_text("world")

    assert [call[0] for call in client.calls] == ["type_text", "edit_text"]
    assert client.calls[0][2]["text"] == "hello"
    assert client.calls[1][2]["text"] == "world"


def test_element_scroll_state_and_scroll_to():
    client = _StubClient()
    element = Element.from_dict(
        {
            "id": 7,
            "control_type": "Pane",
            "scroll": {"vertical_percent": 25.0, "vertical": True},
        }
    ).bind(client, "Excel")

    assert element.scroll_position == (None, 25.0)
    assert element.to_dict(lean=True)["scroll"] == "-,25"

    element.scroll_to(vertical=50)

    assert client.calls[-1][0] == "scroll_to"
    assert client.calls[-1][1][1] == element.target()
    assert client.calls[-1][2] == {"horizontal_percent": None, "vertical_percent": 50}


def test_locator_scroll_to_delegates():
    client = _StubClient([_button()])
    locator = Locator(client, "Excel", "Button")

    locator.scroll_to(horizontal=10, vertical=20)

    assert client.calls[-1][0] == "scroll_to"
    assert client.calls[-1][2] == {"horizontal_percent": 10, "vertical_percent": 20}


def test_selector_prefers_automation_id_then_path_then_role_and_name():
    assert _button(automation_id="SaveButton").selector() == '[automation_id="SaveButton"]'
    assert _button(automation_id='Say "hi"').selector() == '[automation_id="Say \\"hi\\""]'
    assert _button(path="Frame/Button").selector() == 'Button[name="Save"]'
    assert _button(name='Say "hi"').selector() == 'Button[name="Say \\"hi\\""]'
    assert Element(control_type="Pane").selector() == "Pane"


def test_snapshot_from_dict_binds_elements():
    client = _StubClient()
    snapshot = Snapshot.from_dict(
        {
            "window": {"handle": "0x1", "title": "Excel"},
            "elements": [{"id": 2, "control_type": "Button", "name": "Save"}],
        },
        client=client,
        window="Excel",
    )

    assert snapshot.elements[0]._client is client
    assert snapshot.elements[0]._window == "Excel"


def test_snapshot_notes_round_trip():
    snapshot = Snapshot.from_dict({"notes": ["cut by max_elements"]})

    assert snapshot.notes == ["cut by max_elements"]
    assert snapshot.to_dict()["notes"] == ["cut by max_elements"]


def test_locator_selector_nth_and_pick_return_bound_elements():
    first = Element(id=0, control_type="Button", name="One")
    second = _button()
    client = _StubClient([first, second])
    locator = Locator(client, "Excel", "*")

    assert locator.selector() == "*"
    assert locator.nth(2) is second
    assert second._client is client
    assert locator.pick(lambda element: element.name == "Save") is second


def test_locator_pointer_and_semantic_actions():
    client = _StubClient([_button()])
    locator = Locator(client, "Excel", "Button")

    locator.click()
    locator.click(at="center")
    locator.double_click()
    locator.right_click()
    locator.hover()
    locator.select()
    locator.scroll_into_view()
    locator.type_text("hello")
    locator.edit_text("world")

    assert [call[0] for call in client.calls] == [
        "click",
        "click",
        "double_click",
        "right_click",
        "hover",
        "select",
        "scroll_into_view",
        "type_text",
        "edit_text",
    ]


def test_locator_nth_rejects_zero_based_indices():
    with pytest.raises(ValueError):
        Locator(_StubClient(), "Excel", "*").nth(0)
