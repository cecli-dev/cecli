"""EditText / UpdateTodoList tool-arg JSON coercion (local models)."""

from __future__ import annotations

import pytest


class TestLocalModelToolJson:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (
                '{"path": "src/a.ts"}{"start_line": 1}{"end_line": 5}',
                {"path": "src/a.ts", "start_line": 1, "end_line": 5},
            ),
            (
                '{"path": "src/a.ts", "content": "x"}{}',
                {"path": "src/a.ts", "content": "x"},
            ),
        ],
    )
    def test_parse_tool_arguments_merges_glued_objects(self, raw: str, expected: dict):
        from cecli.helpers.responses import parse_tool_arguments

        assert parse_tool_arguments(raw) == expected

    def test_char_split_json_array_join(self):
        from cecli.helpers.responses import try_join_char_split_json_array

        chars = list('[{"task": "x", "done": false}]')
        assert try_join_char_split_json_array(chars) == [{"task": "x", "done": False}]
