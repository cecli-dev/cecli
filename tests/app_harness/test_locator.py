"""Tests for the selector parser, snapshot matcher and re-resolving locators."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness.client import AppClient, AppHarnessError  # noqa: E402
from cecli.helpers.app_harness.locator import compile_match, parse, select  # noqa: E402
from cecli.helpers.app_harness.models import ActionResult, Element  # noqa: E402


def _elements() -> list[Element]:
    return [
        Element(id=0, control_type="Window", name="Excel - Book1", runtime_id="42.1"),
        Element(
            id=1,
            control_type="Edit",
            name="Address",
            value="1 Main St",
            parent=0,
            runtime_id="42.2",
            automation_id="A1",
        ),
        Element(id=2, control_type="Button", name="Save", parent=0, runtime_id="42.3"),
        Element(
            id=3,
            control_type="Edit",
            name="Password",
            parent=1,
            runtime_id="42.4",
            enabled=False,
            sensitive=True,
        ),
    ]


def _ids(selector: str, elements: list[Element] | None = None) -> list[int]:
    return [element.id for element in select(elements or _elements(), selector)]


def test_parse_normalizes_snake_and_title_case_roles():
    compounds = parse("data_item")

    assert len(compounds) == 1
    assert compounds[0].role == "data_item"
    assert compounds[0].combinator is None
    assert compounds[0].group == 0
    assert compounds[0].matches(Element(control_type="DataItem"))
    assert compounds[0].matches(Element(control_type="Data Item"))
    assert not compounds[0].matches(Element(control_type="Edit"))


def test_parse_records_combinators_and_groups():
    compounds = parse("Window > Edit[name='x'], Button")

    assert [(item.role, item.combinator, item.group) for item in compounds] == [
        ("Window", None, 0),
        ("Edit", "child", 0),
        ("Button", None, 1),
    ]


def test_wildcard_role_matches_every_element():
    assert _ids("*") == [0, 1, 2, 3]
    assert _ids("Window > *") == [1, 2]


def test_role_matching_is_case_insensitive():
    assert _ids("button") == [2]
    assert _ids("WINDOW") == [0]


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("[name='Save']", [2]),
        ("[name='save']", [2]),
        ('[name="Save"]', [2]),
        ("[name*='av']", [2]),
        ("[name^='Sa']", [2]),
        ("[name$='ve']", [2]),
        ("[name*='x']", [0]),
        ("[value='']", [0, 2, 3]),
        ("[value*='main']", [1]),
        ("[role='button']", [2]),
        ("[role^='ed']", [1, 3]),
    ],
)
def test_string_attribute_operators(selector, expected):
    assert _ids(selector) == expected


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("[enabled=true]", [0, 1, 2]),
        ("[enabled=false]", [3]),
        ("[sensitive=true]", [3]),
        ("[sensitive=false]", [0, 1, 2]),
        ("Button[enabled=true]", [2]),
        ("Button[enabled=false]", []),
    ],
)
def test_boolean_attributes(selector, expected):
    assert _ids(selector) == expected


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        (":nth(1)", [0]),
        (":nth(2)", [1]),
        ("Edit:nth(1)", [1]),
        ("Edit:nth(2)", [3]),
        ("Edit:nth(3)", []),
        ("Window > *:nth(2)", [2]),
    ],
)
def test_nth_is_one_based_within_the_current_match_set(selector, expected):
    assert _ids(selector) == expected


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("Window > Edit", [1]),
        ("Window Edit", [1, 3]),
        ("Window > Edit > Edit", [3]),
        ("* > [name='Password']", [3]),
        ("Window > Button", [2]),
        ("Edit > Edit", [3]),
    ],
)
def test_child_and_descendant_combinators(selector, expected):
    assert _ids(selector) == expected


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("Button, Edit", [1, 2, 3]),
        ("Edit, Button", [1, 2, 3]),
        ("Window > Button, Button", [2]),
        ("Edit, Edit", [1, 3]),
        ("Window > Edit[name='Address'], Button[name='Save']", [1, 2]),
        ("Window > *:nth(2), Button", [2]),
    ],
)
def test_alternation_unions_and_deduplicates_in_document_order(selector, expected):
    assert _ids(selector) == expected


def test_unknown_parent_links_are_treated_as_roots():
    elements = [
        Element(id=8, control_type="Button", name="Orphan", parent=99),
        Element(id=9, control_type="Window", name="Root"),
    ]

    assert _ids("[name='Orphan']", elements) == [8]
    assert _ids("* > [name='Orphan']", elements) == []
    assert _ids("* [name='Orphan']", elements) == []


def test_duplicate_ids_are_returned_once():
    elements = [
        Element(id=7, control_type="Button", name="First"),
        Element(id=7, control_type="Button", name="Second"),
    ]

    assert _ids("*", elements) == [7]


@pytest.mark.parametrize(
    "selector",
    [
        "",
        "   ",
        "Button[",
        "Button[name='x]",
        "Button[name]",
        "[name=]",
        "[bogus='x']",
        "[enabled=maybe]",
        "[enabled*='true']",
        ":nth(0)",
        ":nth(x)",
        ":nth()",
        ":first",
        ">",
        "Button >",
        "Button,,Edit",
        "Button]",
        "Button > > Edit",
    ],
)
def test_parse_rejects_bad_input(selector):
    with pytest.raises(ValueError) as info:
        parse(selector)

    assert "selector" in str(info.value)


def test_find_returns_document_order_matches_and_count(fake_bridge):
    matches, count = AppClient().find("Excel", "Edit")

    assert [element.id for element in matches] == [1, 3]
    assert count == 2


def test_find_limit_caps_results_but_not_count(fake_bridge):
    matches, count = AppClient().find("Excel", "*", limit=2)

    assert [element.id for element in matches] == [0, 1]
    assert count == 4


def test_find_can_disable_the_limit(fake_bridge):
    matches, count = AppClient().find("Excel", "*", limit=-1)

    assert len(matches) == 4
    assert count == 4


def test_find_forwards_snapshot_options(fake_bridge):
    AppClient().find("Excel", "Button", max_depth=4, max_elements=8, exclude_roles=["Menu"])

    assert fake_bridge.requests[-1]["body"] == {
        "window": "Excel",
        "max_depth": 4,
        "max_elements": 8,
        "exclude_roles": ["Menu"],
    }


def test_find_rejects_bad_selector_before_snapshot(fake_bridge):
    with pytest.raises(AppHarnessError) as info:
        AppClient().find("Excel", "Button[")

    assert info.value.kind == "invalid_request"
    assert fake_bridge.requests == []


def test_locator_invoke_resolves_target_from_a_fresh_snapshot(fake_bridge):
    result = AppClient().locator("Excel", "Button").invoke()

    assert result.action == "invoke"
    assert fake_bridge.action_requests[-1]["target"] == {"id": 2, "runtime_id": "42.3"}
    assert fake_bridge.paths() == ["/api/app/find", "/api/app/action"]


def test_locator_actions_all_use_the_resolved_target(fake_bridge):
    locator = AppClient().locator("Excel", "Button")

    locator.click()
    locator.set_value("pressed")
    locator.get_value()
    locator.focus()

    assert [request["action"] for request in fake_bridge.action_requests] == [
        "click",
        "set_value",
        "get_value",
        "focus",
    ]
    assert fake_bridge.action_requests[1]["args"]["value"] == "pressed"
    assert all(
        request["target"] == {"id": 2, "runtime_id": "42.3"}
        for request in fake_bridge.action_requests
    )
    assert fake_bridge.paths() == ["/api/app/find", "/api/app/action"] * 4


def test_multi_match_locator_raises_instead_of_guessing(fake_bridge):
    with pytest.raises(AppHarnessError) as info:
        AppClient().locator("Excel", "Edit").click()

    message = str(info.value)

    assert info.value.kind == "invalid_request"
    assert "2 elements" in message
    assert "Address" in message
    assert "Password" in message
    assert fake_bridge.action_requests == []


def test_locator_parses_the_selector_eagerly(fake_bridge):
    with pytest.raises(AppHarnessError) as info:
        AppClient().locator("Excel", "Button[")

    assert info.value.kind == "invalid_request"
    assert fake_bridge.requests == []


def test_locator_wait_polls_until_an_element_appears():
    element = Element(id=2, control_type="Button", name="Save")
    client = _StubClient([([], 0), ([element], 1)])

    found = AppClient.locator(client, "Excel", "Button")

    assert found.wait().id == 2
    assert len(client.calls) == 2


def test_locator_wait_times_out_when_nothing_matches():
    client = _StubClient([([], 0)], timeout_ms=1)

    locator = AppClient.locator(client, "Excel", "Gone")

    with pytest.raises(AppHarnessError) as info:
        locator.wait()

    assert info.value.kind == "not_found"
    assert "Gone" in str(info.value)


def test_locator_wraps_missing_target_during_action_as_stale_target():
    element = Element(id=2, control_type="Button", name="Save")
    client = _StubClient([([element], 1)], action_error=AppHarnessError("target_not_found", "gone"))

    locator = AppClient.locator(client, "Excel", "Button")

    with pytest.raises(AppHarnessError) as info:
        locator.invoke()

    assert info.value.kind == "stale_target"
    assert "disappeared" in str(info.value)


def test_ambiguous_message_names_only_the_first_three_candidates():
    elements = [
        Element(id=index, control_type="Button", name=name)
        for index, name in enumerate(("Alpha", "Bravo", "Charlie", "Delta"))
    ]
    client = _StubClient([(elements, 4)])

    locator = AppClient.locator(client, "Excel", "Button")

    with pytest.raises(AppHarnessError) as info:
        locator.wait()

    message = str(info.value)

    assert "Alpha" in message
    assert "Bravo" in message
    assert "Charlie" in message
    assert "Delta" not in message
    assert client.actions == []


def test_compile_match_uses_the_last_compound_and_keeps_ancestor_roles():
    plan = compile_match("Window > Button[name*='av']")

    assert plan is not None
    assert plan.simple is False
    assert plan.spec == {"roles": ["Button", "Window"], "name": {"op": "contains", "value": "av"}}

    single = compile_match("Button[enabled=false]")

    assert single is not None
    assert single.simple is True
    assert single.spec == {"roles": ["Button"], "enabled": False}


def test_compile_match_rejects_selectors_the_server_cannot_express():
    assert compile_match("Button, Edit") is None
    assert compile_match("Edit:nth(2)") is None
    assert compile_match("Window > [name='Save']") is None


def test_find_elements_uses_the_server_route(fake_bridge):
    matches, count, truncated = AppClient().find_elements("Excel", "Button")

    assert [element.id for element in matches] == [2]
    assert count == 1
    assert truncated is False
    assert fake_bridge.paths() == ["/api/app/find"]
    assert fake_bridge.requests[-1]["body"]["match"] == {"roles": ["Button"]}


def test_find_elements_reevaluates_a_chain_client_side(fake_bridge):
    matches, count, truncated = AppClient().find_elements("Excel", "Window > Edit")

    assert [element.id for element in matches] == [1]
    assert count == 1
    assert truncated is False
    assert fake_bridge.requests[-1]["body"]["match"]["roles"] == ["Edit", "Window"]


def test_find_elements_applies_a_chain_filter_client_side(fake_bridge):
    matches, count, truncated = AppClient().find_elements("Excel", "Window > Edit[name='Address']")

    assert [element.id for element in matches] == [1]
    assert count == 1
    assert truncated is False
    assert "name" not in fake_bridge.requests[-1]["body"]["match"]


def test_find_elements_falls_back_when_the_route_is_missing(fake_bridge):
    fake_bridge.find_enabled = False

    matches, count, truncated = AppClient().find_elements("Excel", "Button")

    assert [element.id for element in matches] == [2]
    assert count == 1
    assert truncated is False
    assert fake_bridge.paths() == ["/api/app/find", "/api/app/snapshot"]


def test_find_server_returns_match_count_and_truncation(fake_bridge):
    matches, count, truncated = AppClient().find_server("Excel", roles=["Edit"], limit=1)

    assert [element.id for element in matches] == [1]
    assert count == 2
    assert truncated is True
    assert fake_bridge.requests[-1]["body"] == {
        "window": "Excel",
        "match": {"roles": ["Edit"]},
        "limit": 1,
    }


def test_cell_at_posts_row_and_column(fake_bridge):
    result = AppClient().cell_at("Excel", 4, 2)

    assert fake_bridge.action_requests[-1]["action"] == "cell_at"
    assert fake_bridge.action_requests[-1]["args"]["row"] == 4
    assert fake_bridge.action_requests[-1]["args"]["column"] == 2
    assert result.element is not None
    assert result.element["name"] == "B4"
    assert result.element["path"] == "Sheet1/Table/TableCell[B4]"


def test_state_pseudo_classes_and_offscreen_attribute():
    elements = [
        Element(id=0, control_type="Button", name="On", enabled=True, offscreen=False),
        Element(id=1, control_type="Button", name="Off", enabled=False, offscreen=True),
    ]

    assert _ids("Button:enabled", elements) == [0]
    assert _ids("Button:visible", elements) == [0]
    assert _ids("Button[offscreen=true]", elements) == [1]
    assert _ids("Button[offscreen=false]", elements) == [0]
    assert _ids("Button:enabled:visible", elements) == [0]
    assert _ids("Button:enabled:nth(1)", elements) == [0]


def test_compile_match_treats_visibility_as_a_snapshot_only_predicate():
    assert compile_match("Button:enabled") is not None
    assert compile_match("Button:visible") is None
    assert compile_match("Button[offscreen=false]") is None


def test_find_elements_falls_back_for_visibility(fake_bridge):
    matches, count, truncated = AppClient().find_elements("Excel", "Button:visible")

    assert [element.id for element in matches] == [2]
    assert count == 1
    assert truncated is False
    assert fake_bridge.paths() == ["/api/app/snapshot"]


def test_locator_wait_for_returns_once_the_state_holds():
    disabled = Element(id=2, control_type="Button", name="Save", enabled=False)
    enabled = Element(id=2, control_type="Button", name="Save", enabled=True)
    client = _StubClient([([disabled], 1), ([enabled], 1)])

    locator = AppClient.locator(client, "Excel", "Button")

    assert locator.wait_for(enabled=True).enabled is True
    assert len(client.calls) == 2


def test_locator_wait_for_times_out_when_the_state_never_holds():
    element = Element(id=2, control_type="Button", name="Save", enabled=False)
    client = _StubClient([([element], 1)], timeout_ms=1)

    locator = AppClient.locator(client, "Excel", "Button")

    with pytest.raises(AppHarnessError) as info:
        locator.wait_for(enabled=True)

    assert info.value.kind == "timeout"
    assert "enabled" in str(info.value)


def test_locator_wait_for_missing_element_is_not_found():
    client = _StubClient([([], 0)], timeout_ms=1)

    locator = AppClient.locator(client, "Excel", "Gone")

    with pytest.raises(AppHarnessError) as info:
        locator.wait_for(visible=True)

    assert info.value.kind == "not_found"
    assert "Gone" in str(info.value)


class _StubClient:
    """Minimal client double for polling and failure-path tests."""

    def __init__(
        self,
        results: list[tuple[list[Element], int]],
        *,
        timeout_ms: int = 1000,
        action_error: AppHarnessError | None = None,
    ) -> None:
        self.results = list(results)
        self.timeout_ms = timeout_ms
        self.action_error = action_error
        self.calls: list[tuple] = []
        self.actions: list[tuple] = []

    def find(self, *args):
        self.calls.append(args)

        if len(self.results) > 1:
            return self.results.pop(0)

        return self.results[0]

    def find_elements(self, *args):
        matches, count = self.find(*args)
        return matches, count, False

    def refresh(self) -> int:
        return 0

    def invoke(self, window: str, target: dict) -> ActionResult:
        self.actions.append(("invoke", window, target))

        if self.action_error is not None:
            raise self.action_error

        return ActionResult(action="invoke", delivered=True, verified=True)


def test_element_selector_round_trips_through_parse():
    for element in (
        Element(control_type="Button", name="Save", automation_id="SaveButton"),
        Element(control_type="Button", name='Say "hi"'),
        Element(control_type="Pane"),
    ):
        parse(element.selector())
