"""Tests for the TOON encoder used by snapshot output."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import toon  # noqa: E402


def test_encodes_a_nested_object() -> None:
    text = toon.encode({"window": {"title": "Excel", "pid": 42}, "truncated": False})

    assert text == "window:\n  title: Excel\n  pid: 42\ntruncated: false"


def test_uniform_objects_use_tabular_form() -> None:
    rows = [
        {"id": 0, "parent": None, "name": "Window"},
        {"id": 1, "parent": 0, "name": "Save"},
    ]

    assert toon.encode({"elements": rows}) == (
        "elements[2]{id,parent,name}:\n  0,null,Window\n  1,0,Save"
    )


def test_lean_element_geometry_keeps_tabular_form() -> None:
    from cecli.helpers.app_harness.models import Element, Rect

    rows = [
        Element(id=1, control_type="Button", name="Save", bounds=Rect(300, 20, 80, 24)).to_dict(
            lean=True
        ),
        Element(id=2, control_type="Edit", name="Name", bounds=None).to_dict(lean=True),
    ]

    assert toon.encode({"elements": rows}) == (
        "elements[2]{id,parent,depth,control_type,name,value,enabled,offscreen,sensitive,bounds,center,scroll}:\n"
        '  1,null,0,Button,Save,null,true,false,false,"300,20,80,24","340,32",null\n'
        "  2,null,0,Edit,Name,null,true,false,false,null,null,null"
    )


def test_nested_uniform_objects_become_a_field_group() -> None:
    rows = [
        {"id": 0, "bounds": {"left": 0, "top": 0}},
        {"id": 1, "bounds": {"left": 5, "top": 6}},
    ]

    assert toon.encode(rows) == "[2]{id,bounds{left,top}}:\n  0,0,0\n  1,5,6"


def test_non_uniform_rows_fall_back_to_list_form() -> None:
    rows = [{"id": 0, "name": "a"}, {"id": 1, "value": "b"}]
    text = toon.encode({"elements": rows})

    assert text.startswith("elements[2]:")
    assert "  - id: 0" in text
    assert "    name: a" in text


def test_primitive_arrays_stay_inline() -> None:
    text = toon.encode({"patterns": ["Action", "Value"]})

    assert text == "patterns[2]: Action,Value"


def test_strings_quote_only_when_required() -> None:
    text = toon.encode(
        {
            "plain": "Frame[Title]",
            "comma": "a,b",
            "colon": "a: b",
            "empty": "",
            "number": "42",
            "bool": "true",
            "dash": "-1",
        }
    )

    assert "plain: Frame[Title]" not in text
    assert 'plain: "Frame[Title]"' in text
    assert 'comma: "a,b"' in text
    assert 'colon: "a: b"' in text
    assert 'empty: ""' in text
    assert 'number: "42"' in text
    assert 'bool: "true"' in text
    assert 'dash: "-1"' in text


def test_empty_values_are_explicit() -> None:
    assert toon.encode({"elements": []}) == "elements: []"
    assert toon.encode({"parent": None}) == "parent: null"
    assert toon.encode({"nested": {}}) == "nested:"


def test_keys_needing_quotes_are_escaped() -> None:
    assert toon.encode({"user-name": 1}) == '"user-name": 1'
    assert toon.encode({"user.name": 1}) == "user.name: 1"
