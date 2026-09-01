"""Tests for the ToolValidations class."""

from __future__ import annotations

from cecli.tools.validations import ToolValidations

# =========================================================================
# _basic_validations tests
# =========================================================================


class TestBasicValidations:
    """Structural corrections: bare list → dict wrapping."""

    def test_bare_list_wraps_into_single_array_property(self):
        """A bare list param should be wrapped when schema has one array property."""
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "delegations": {
                            "type": "array",
                            "items": {"type": "object"},
                        }
                    }
                }
            }
        }
        params = [{"name": "a1", "prompt": "do stuff"}]
        result = ToolValidations._basic_validations(params, schema)
        assert result == {"delegations": params}

    def test_dict_params_pass_through(self):
        """Already-wrapped dict params should pass through unchanged."""
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "delegations": {
                            "type": "array",
                            "items": {"type": "object"},
                        }
                    }
                }
            }
        }
        params = {"delegations": [{"name": "a1", "prompt": "do stuff"}]}
        result = ToolValidations._basic_validations(params, schema)
        assert result is params

    def test_multi_property_schema_does_not_wrap(self):
        """Bare list should not wrap when schema has multiple properties."""
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "add": {"type": "array"},
                        "remove": {"type": "array"},
                    }
                }
            }
        }
        params = ["file_a.py", "file_b.py"]
        result = ToolValidations._basic_validations(params, schema)
        assert result is params

    def test_non_array_property_does_not_wrap(self):
        """Bare list should not wrap when the single property is not an array."""
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "name": {"type": "string"},
                    }
                }
            }
        }
        params = ["some", "strings"]
        result = ToolValidations._basic_validations(params, schema)
        assert result is params

    def test_no_schema_does_not_wrap(self):
        """Bare list should passthrough when schema is None."""
        result = ToolValidations._basic_validations([1, 2, 3], None)
        assert result == [1, 2, 3]

    def test_empty_properties_does_not_wrap(self):
        """Bare list should passthrough when schema has no properties."""
        schema = {"function": {"parameters": {"properties": {}}}}
        result = ToolValidations._basic_validations([1, 2, 3], schema)
        assert result == [1, 2, 3]


# =========================================================================
# coerce_list tests
# =========================================================================


class TestCoerceList:
    """List coercion: strings, dicts, and edge cases."""

    def test_actual_list_passthrough(self):
        """A proper list should pass through unchanged."""
        data = [{"a": 1}, {"b": 2}]
        result = ToolValidations.coerce_list(data)
        assert result == data

    def test_json_string_array(self):
        """A JSON string containing an array should be parsed."""
        result = ToolValidations.coerce_list('[{"a": 1}, {"b": 2}]')
        assert result == [{"a": 1}, {"b": 2}]

    def test_json_string_dict(self):
        """A JSON string containing a dict should be wrapped in a list."""
        result = ToolValidations.coerce_list('{"task": "hello"}')
        assert result == [{"task": "hello"}]

    def test_bare_dict_wraps_in_list(self):
        """A bare dict should be wrapped in a list."""
        result = ToolValidations.coerce_list({"task": "hello"})
        assert result == [{"task": "hello"}]

    def test_empty_string_returns_empty_list(self):
        """An empty string should return an empty list."""
        assert ToolValidations.coerce_list("") == []
        assert ToolValidations.coerce_list("   ") == []

    def test_integer_returns_empty_list(self):
        """A non-list, non-dict, non-string input should return empty list."""
        assert ToolValidations.coerce_list(42) == []
        assert ToolValidations.coerce_list(None) == []

    def test_char_split_json_array(self):
        """A char-split JSON array should be reconstructed."""
        items = ["[", "{", '"', "t", "a", "s", "k", '"', ":", " ", '"', "x", '"', "}", "]"]
        result = ToolValidations.coerce_list(items)
        assert result == [{"task": "x"}]

    def test_single_item_wrapping_json_string_list(self):
        """A single-element list wrapping a JSON array string should unwrap."""
        result = ToolValidations.coerce_list(['[{"a": 1}]'])
        assert result == [{"a": 1}]

    def test_single_item_wrapping_json_string_dict(self):
        """A single-element list wrapping a JSON dict string should unwrap."""
        result = ToolValidations.coerce_list(['{"a": 1}'])
        assert result == [{"a": 1}]


# =========================================================================
# coerce_dict tests
# =========================================================================


class TestCoerceDict:
    """Dict coercion: strings, dicts, and edge cases."""

    def test_actual_dict_passthrough(self):
        """A proper dict should pass through unchanged."""
        data = {"name": "test", "prompt": "do stuff"}
        result = ToolValidations.coerce_dict(data)
        assert result is data

    def test_json_string_object(self):
        """A JSON string object should be parsed into a dict."""
        result = ToolValidations.coerce_dict('{"name": "test", "prompt": "do stuff"}')
        assert result == {"name": "test", "prompt": "do stuff"}

    def test_empty_string_returns_none(self):
        """An empty string should return None."""
        assert ToolValidations.coerce_dict("") is None
        assert ToolValidations.coerce_dict("   ") is None

    def test_invalid_json_string_returns_none(self):
        """An invalid JSON string should return None."""
        assert ToolValidations.coerce_dict("{broken") is None
        assert ToolValidations.coerce_dict("hello") is None

    def test_integer_returns_none(self):
        """A non-dict, non-string input should return None."""
        assert ToolValidations.coerce_dict(42) is None

    def test_list_returns_none(self):
        """A list input should return None."""
        assert ToolValidations.coerce_dict([1, 2, 3]) is None

    def test_none_returns_none(self):
        """None input should return None."""
        assert ToolValidations.coerce_dict(None) is None


# =========================================================================
# coerce_str tests
# =========================================================================


class TestCoerceStr:
    """String coercion."""

    def test_string_passthrough(self):
        """A string should pass through unchanged."""
        assert ToolValidations.coerce_str("hello") == "hello"

    def test_integer_to_string(self):
        """An integer should be converted to string."""
        assert ToolValidations.coerce_str(42) == "42"

    def test_float_to_string(self):
        """A float should be converted to string."""
        assert ToolValidations.coerce_str(3.14) == "3.14"

    def test_none_returns_none(self):
        """None should return None."""
        assert ToolValidations.coerce_str(None) is None


# =========================================================================
# coerce_int tests
# =========================================================================


class TestCoerceInt:
    """Integer coercion."""

    def test_int_passthrough(self):
        """An integer should pass through unchanged."""
        assert ToolValidations.coerce_int(42) == 42

    def test_string_number(self):
        """A numeric string should be converted to int."""
        assert ToolValidations.coerce_int("42") == 42

    def test_float_truncates(self):
        """A float should be truncated to int."""
        assert ToolValidations.coerce_int(3.99) == 3

    def test_invalid_string_returns_none(self):
        """A non-numeric string should return None."""
        assert ToolValidations.coerce_int("hello") is None

    def test_none_returns_none(self):
        """None should return None."""
        assert ToolValidations.coerce_int(None) is None

    def test_bool_returns_none(self):
        """A boolean should return None (bool is a subclass of int but we exclude it)."""
        assert ToolValidations.coerce_int(True) is None


# =========================================================================
# coerce_bool tests
# =========================================================================


class TestCoerceBool:
    """Boolean coercion."""

    def test_bool_passthrough(self):
        """A boolean should pass through unchanged."""
        assert ToolValidations.coerce_bool(True) is True
        assert ToolValidations.coerce_bool(False) is False

    def test_string_true_variants(self):
        """Truthy strings should be coerced to True."""
        assert ToolValidations.coerce_bool("true") is True
        assert ToolValidations.coerce_bool("True") is True
        assert ToolValidations.coerce_bool("1") is True
        assert ToolValidations.coerce_bool("yes") is True

    def test_string_false_variants(self):
        """Falsy strings should be coerced to False."""
        assert ToolValidations.coerce_bool("false") is False
        assert ToolValidations.coerce_bool("False") is False
        assert ToolValidations.coerce_bool("0") is False
        assert ToolValidations.coerce_bool("no") is False

    def test_integer_truthy(self):
        """Truthy integers should be coerced to True."""
        assert ToolValidations.coerce_bool(1) is True
        assert ToolValidations.coerce_bool(5) is True

    def test_integer_falsy(self):
        """Falsy integers should be coerced to False."""
        assert ToolValidations.coerce_bool(0) is False

    def test_invalid_string_returns_none(self):
        """An unrecognised truthy/falsy string should return None."""
        assert ToolValidations.coerce_bool("maybe") is None
        assert ToolValidations.coerce_bool("") is None


# =========================================================================
# validate_params integration tests
# =========================================================================


class TestValidateParams:
    """Full workflow: validate_params orchestrator."""

    # ---- empty / None validations ----

    def test_empty_validations_returns_params(self):
        """An empty VALIDATIONS dict should return params unchanged."""
        params = {"key": "value"}
        result = ToolValidations.validate_params(params, {})
        assert result == {"key": "value"}

    def test_none_validations_returns_params(self):
        """A None VALIDATIONS dict should return params unchanged."""
        params = {"key": "value"}
        result = ToolValidations.validate_params(params, None)
        assert result == {"key": "value"}

    def test_arguments_wrapper_string_value_unwrapped(self):
        """A single top-level "arguments" wrapper (as JSON string) is unwrapped.

        Mirrors the execution path (responses.parse_tool_arguments) so previews
        resolve the same args that will actually run.
        """
        params = '{"arguments": "{"edits": [{"file_path": "a.txt"}]}"}'
        result = ToolValidations.validate_params(
            params,
            {"edits": ["coerce_list"], "edits[]": ["coerce_dict"]},
        )
        assert result == {"edits": [{"file_path": "a.txt"}]}

    def test_parameters_wrapper_dict_value_unwrapped(self):
        """A single top-level "parameters" wrapper (as dict) is unwrapped."""
        params = {"parameters": {"edits": [{"file_path": "a.txt"}]}}
        result = ToolValidations.validate_params(
            params,
            {"edits": ["coerce_list"], "edits[]": ["coerce_dict"]},
        )
        assert result == {"edits": [{"file_path": "a.txt"}]}

    def test_multi_key_params_not_unwrapped(self):
        """Params with more than one key are never treated as a wrapper."""
        params = {"edits": [{"file_path": "a.txt"}], "change_id": "x"}
        result = ToolValidations.validate_params(
            params,
            {"edits": ["coerce_list"], "edits[]": ["coerce_dict"]},
        )
        assert result == {"edits": [{"file_path": "a.txt"}], "change_id": "x"}

    # ---- simple keys ----

    def test_simple_key_coerce_list(self):
        """A simple key should apply validation to the top-level param value."""
        params = {"delegations": '[{"name": "a1"}]'}
        result = ToolValidations.validate_params(
            params,
            {"delegations": ["coerce_list"]},
        )
        assert result == {"delegations": [{"name": "a1"}]}

    def test_simple_key_coerce_dict(self):
        """A simple key should coerce a param value to dict."""
        params = {"item": '{"key": "val"}'}
        result = ToolValidations.validate_params(
            params,
            {"item": ["coerce_dict"]},
        )
        assert result == {"item": {"key": "val"}}

    # ---- [] iteration ----

    def test_list_iteration_coerce_dict(self):
        """A [] key should apply validation to each list item."""
        params = {
            "delegations": [
                '{"name": "a1", "prompt": "do x"}',
                '{"name": "a2", "prompt": "do y"}',
            ]
        }
        result = ToolValidations.validate_params(
            params,
            {"delegations[]": ["coerce_dict"]},
        )
        assert result == {
            "delegations": [
                {"name": "a1", "prompt": "do x"},
                {"name": "a2", "prompt": "do y"},
            ]
        }

    def test_list_iteration_skips_null_items(self):
        """Items that fail validation and return None should be dropped."""
        params = {
            "items": [
                '{"valid": "json"}',
                "not json",
                '{"also": "valid"}',
            ]
        }
        result = ToolValidations.validate_params(
            params,
            {"items[]": ["coerce_dict"]},
        )
        # The invalid JSON string returns None and is dropped
        assert result == {
            "items": [
                {"valid": "json"},
                {"also": "valid"},
            ]
        }

    def test_list_iteration_empty_list(self):
        """An empty list should remain empty after iteration."""
        params = {"items": []}
        result = ToolValidations.validate_params(
            params,
            {"items[]": ["coerce_dict"]},
        )
        assert result == {"items": []}

    # ---- chained validations ----

    def test_chained_validations(self):
        """Multiple validation methods should be applied in sequence."""
        params = {"count": "42"}
        result = ToolValidations.validate_params(
            params,
            {"count": ["coerce_str", "coerce_int"]},
        )
        # coerce_str("42") → "42", coerce_int("42") → 42
        assert result == {"count": 42}

    # ---- integration with _basic_validations ----

    def test_bare_list_gets_wrapped_and_validated(self):
        """A bare list param should be wrapped, then validated per item."""
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "delegations": {
                            "type": "array",
                            "items": {"type": "object"},
                        }
                    }
                }
            }
        }
        bare_list = ['{"name": "a1", "prompt": "do x"}']
        result = ToolValidations.validate_params(
            bare_list,
            {"delegations[]": ["coerce_dict"]},
            schema,
        )
        assert result == {
            "delegations": [
                {"name": "a1", "prompt": "do x"},
            ]
        }

    def test_bare_list_with_empty_validations(self):
        """Even with empty VALIDATIONS, _basic_validations should still wrap."""
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "delegations": {
                            "type": "array",
                            "items": {"type": "object"},
                        }
                    }
                }
            }
        }
        bare_list = [{"name": "a1", "prompt": "do x"}]
        result = ToolValidations.validate_params(bare_list, {}, schema)
        assert result == {"delegations": bare_list}

    # ---- key not present ----

    def test_validation_key_not_in_params(self):
        """If the validation key doesn't exist in params, nothing should happen."""
        params = {"other": "value"}
        result = ToolValidations.validate_params(
            params,
            {"missing_key": ["coerce_list"]},
        )
        assert result == {"other": "value"}

    # ---- non-list target for [] ----

    def test_list_iteration_on_non_list_does_nothing(self):
        """If the param for a [] key is not a list, it should be left alone."""
        params = {"items": "not a list"}
        result = ToolValidations.validate_params(
            params,
            {"items[]": ["coerce_dict"]},
        )
        assert result == {"items": "not a list"}


# =========================================================================
# path parsing tests
# =========================================================================


class TestPathParsing:
    """Path resolution: segment, segment.nested, segment[], segment[].nested, segment.nested[], and complex."""

    # ---- "segment" - single path ----

    def test_single_path_segment(self):
        """A simple key should resolve to a top-level param value."""
        params = {"delegations": '[{"name": "a1"}]'}
        result = ToolValidations.validate_params(
            params,
            {"delegations": ["coerce_list"]},
        )
        assert result == {"delegations": [{"name": "a1"}]}

    # ---- "segment.nested" - nested path ----

    def test_nested_path_segment(self):
        """A dot-separated key should resolve to a nested param value."""
        params = {"outer": {"inner": '[{"name": "a1"}]'}}
        result = ToolValidations.validate_params(
            params,
            {"outer.inner": ["coerce_list"]},
        )
        assert result == {"outer": {"inner": [{"name": "a1"}]}}

    def test_nested_path_deep(self):
        """Deeply nested dot-separated key should resolve correctly."""
        params = {"a": {"b": {"c": '{"x": 1}'}}}
        result = ToolValidations.validate_params(
            params,
            {"a.b.c": ["coerce_dict"]},
        )
        assert result == {"a": {"b": {"c": {"x": 1}}}}

    # ---- "segment[]" - iterate over list items at segment ----

    def test_segment_bracket_iterates_list_items(self):
        """A key with trailing [] should apply validation to each list item."""
        params = {
            "items": [
                '{"name": "a1", "prompt": "do x"}',
                '{"name": "a2", "prompt": "do y"}',
            ]
        }
        result = ToolValidations.validate_params(
            params,
            {"items[]": ["coerce_dict"]},
        )
        assert result == {
            "items": [
                {"name": "a1", "prompt": "do x"},
                {"name": "a2", "prompt": "do y"},
            ]
        }

    # ---- "segment[].nested" - iterate then access sub-key ----

    def test_segment_bracket_nested_key(self):
        """segment[].nested: iterate over segment items, apply validation to each item's .nested."""
        params = {
            "items": [
                {"nested": '{"a": 1}'},
                {"nested": '{"b": 2}'},
            ]
        }
        result = ToolValidations.validate_params(
            params,
            {"items[].nested": ["coerce_dict"]},
        )
        assert result == {
            "items": [
                {"nested": {"a": 1}},
                {"nested": {"b": 2}},
            ]
        }

    def test_segment_bracket_nested_skips_missing_keys(self):
        """segment[].nested: items missing the nested key should be left alone."""
        params = {
            "items": [
                {"nested": '{"a": 1}'},
                {"other": "value"},
            ]
        }
        result = ToolValidations.validate_params(
            params,
            {"items[].nested": ["coerce_dict"]},
        )
        # The item without 'nested' should remain unchanged
        assert result == {
            "items": [
                {"nested": {"a": 1}},
                {"other": "value"},
            ]
        }

    def test_segment_bracket_nested_not_a_list(self):
        """segment[].nested: if segment is not a list, params should be left unchanged."""
        params = {"items": "not a list"}
        result = ToolValidations.validate_params(
            params,
            {"items[].nested": ["coerce_dict"]},
        )
        assert result == {"items": "not a list"}

    # ---- "segment.nested[]" - navigate then iterate ----

    def test_nested_dot_bracket_iterates_list(self):
        """segment.nested[]: navigate to segment.nested, then iterate over list items."""
        params = {
            "group": {
                "items": [
                    '{"name": "a1"}',
                    '{"name": "a2"}',
                ]
            }
        }
        result = ToolValidations.validate_params(
            params,
            {"group.items[]": ["coerce_dict"]},
        )
        assert result == {
            "group": {
                "items": [
                    {"name": "a1"},
                    {"name": "a2"},
                ]
            }
        }

    # ---- "segment[].nested[].nested2" - complex ----

    def test_complex_nested_iteration(self):
        """segment[].nested[].nested2: iterate, descend, iterate, access sub-key."""
        params = {
            "items": [
                {
                    "nested": [
                        {"nested2": '{"a": 1}'},
                        {"nested2": '{"b": 2}'},
                    ]
                },
                {
                    "nested": [
                        {"nested2": '{"c": 3}'},
                    ]
                },
            ]
        }
        result = ToolValidations.validate_params(
            params,
            {"items[].nested[].nested2": ["coerce_dict"]},
        )
        assert result == {
            "items": [
                {
                    "nested": [
                        {"nested2": {"a": 1}},
                        {"nested2": {"b": 2}},
                    ]
                },
                {
                    "nested": [
                        {"nested2": {"c": 3}},
                    ]
                },
            ]
        }

    # ---- edge cases ----

    def test_complex_missing_intermediate_key(self):
        """Complex path: missing intermediate key should leave params unchanged."""
        params = {"items": [{"nested": [{"nested2": "value"}]}]}
        result = ToolValidations.validate_params(
            params,
            {"items[].missing[].nested2": ["coerce_dict"]},
        )
        # "missing" doesn't exist, so nothing happens
        assert result == {"items": [{"nested": [{"nested2": "value"}]}]}

    def test_complex_middle_not_a_list(self):
        """Complex path: if an intermediate [] target is not a list, params left unchanged."""
        params = {"items": [{"nested": "not a list"}]}
        result = ToolValidations.validate_params(
            params,
            {"items[].nested[].nested2": ["coerce_dict"]},
        )
        # "nested" is not a list, so the second [] iteration can't happen
        assert result == {"items": [{"nested": "not a list"}]}

    def test_complex_empty_inner_list(self):
        """Complex path: an empty inner list should remain empty."""
        params = {"items": [{"nested": []}]}
        result = ToolValidations.validate_params(
            params,
            {"items[].nested[].nested2": ["coerce_dict"]},
        )
        assert result == {"items": [{"nested": []}]}
