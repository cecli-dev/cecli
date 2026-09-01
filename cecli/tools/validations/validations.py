"""
Tool parameter validation module for BaseTool subclasses.

Provides a framework for declarative parameter validation via VALIDATIONS dicts
on tool classes, along with built-in validation methods.

The VALIDATIONS dict maps parameter paths (dot-separated, optionally with []
for list iteration) to lists of validation method names that are executed
sequentially on the parameter value.

Example:

    VALIDATIONS = {
        "delegations": ["coerce_list"],
        "delegations[]": ["coerce_dict"],
        "edits": ["coerce_list"],
        "edits[].file_path": ["coerce_str"],
    }
"""

from __future__ import annotations

import json

import json_repair

from cecli.helpers import responses
from cecli.tools.utils.helpers import ToolError


class ToolValidations:
    """
    Registry of validation methods for tool parameters.

    Each classmethod in this class can be referenced by name in a tool's
    VALIDATIONS dict. The ``validate_params`` classmethod orchestrates
    the application of validations based on the dict.
    """

    @classmethod
    def validate_params(cls, params: dict, validations: dict, schema: dict | None = None) -> dict:
        """
        Apply validations to *params* according to the *validations* dict.

        Parameters are modified in place and also returned for convenience.

        Args:
            params: The raw tool parameters dict.
            validations: A VALIDATIONS dict mapping parameter paths to
                lists of validation method names.
            schema: The tool's SCHEMA dict (used for context, currently
                reserved for future use).

        Returns:
            The (possibly mutated) *params* dict.
        """
        if isinstance(params, str):
            params = json_repair.loads(params)

        if not isinstance(params, (dict, list)):
            raise ToolError("Invalid Tool Input - Unparsable JSON")

        # Mirror the execution path (responses.parse_tool_arguments): some models
        # double-wrap the real params under a single "arguments"/"parameters"/"params"
        # key. Unwrap so previews resolve the same args that will actually execute.
        if isinstance(params, dict):
            params = responses.coerce_tool_structure(params)

        # Apply basic structural corrections before declarative validations
        params = cls._basic_validations(params, schema)

        if not validations:
            return params

        for raw_key, method_names in validations.items():
            segments = cls._parse_validation_key(raw_key)
            if not segments:
                continue
            cls._apply_along_segments(params, segments, method_names)
        return params

    @staticmethod
    def _parse_validation_key(raw_key: str) -> list[tuple[str, bool]]:
        """
        Parse a validation path into a list of (key, iterate) tuples.

        Supports the following path shapes:

            "segment"              -> [("segment", False)]
            "segment.nested"        -> [("segment", False), ("nested", False)]
            "segment[]"             -> [("segment", True)]
            "segment[].nested"      -> [("segment", True), ("nested", False)]
            "segment.nested[]"      -> [("segment", False), ("nested", True)]
            "segment[].nested[].n2" -> [("segment", True), ("nested", True), ("n2", False)]

        Any trailing ``[]`` on a path segment marks it for iteration — the
        validation will be applied to each item in the list found at that key.

        Returns:
            A list of (key, should_iterate) tuples. Returns an empty list
            if the key is empty or contains only separators.
        """
        if not raw_key:
            return []

        parts = raw_key.split(".")
        segments: list[tuple[str, bool]] = []
        for part in parts:
            if not part:
                continue
            if part.endswith("[]"):
                segments.append((part[:-2], True))
            else:
                segments.append((part, False))

        return segments

    @classmethod
    def _apply_along_segments(
        cls, params: dict, segments: list[tuple[str, bool]], method_names: list[str]
    ) -> None:
        """
        Recursively apply *method_names* along the parsed *segments* path.

        Each segment is a ``(key, iterate)`` tuple.  When *iterate* is ``True``
        the method expects ``params[key]`` to be a list and either applies the
        validations to each item (if this is the last segment) or recurses
        into each item's dict (if there are further segments).  When *iterate*
        is ``False`` the method either applies validations to ``params[key]``
        (last segment) or recurses into the nested dict.

        ``params`` is mutated in place.
        """
        if not segments:
            return

        key, iterate = segments[0]
        remaining = segments[1:]

        if not isinstance(params, dict) or key not in params:
            return

        if iterate:
            items = params[key]
            if not isinstance(items, list):
                return

            if not remaining:
                # Apply validation methods to each item in the list
                new_items: list = []
                for item in items:
                    for method_name in method_names:
                        method = getattr(cls, method_name, None)
                        if method is None:
                            raise ToolError(f"Unknown validation method: {method_name}")
                        item = method(item)
                        if item is None:
                            break
                    if item is not None:
                        new_items.append(item)
                params[key] = new_items
            else:
                # Recurse into each item, applying remaining segments
                for item in items:
                    if isinstance(item, dict):
                        cls._apply_along_segments(item, remaining, method_names)
        else:
            if not remaining:
                # Apply validation methods to the value at this key
                value = params[key]
                for method_name in method_names:
                    method = getattr(cls, method_name, None)
                    if method is None:
                        raise ToolError(f"Unknown validation method: {method_name}")
                    value = method(value)
                    if value is None:
                        break
                params[key] = value
            else:
                # Navigate deeper
                nested = params[key]
                if isinstance(nested, dict):
                    cls._apply_along_segments(nested, remaining, method_names)

    @classmethod
    def _basic_validations(cls, params: object, schema: dict | None = None) -> dict:
        """
        Apply basic structural corrections to *params* based on *schema*.

        If the schema declares exactly one property of type ``array``:
          - If *params* is a bare list, wrap it as ``{param_name: [...]}``.
          - If *params* is a dict that doesn't contain the expected key,
            wrap the dict in a list under that key:
            ``{param_name: [{key: val, ...}]}``.

        Returns the (possibly corrected) *params* dict.
        """
        if not schema or "function" not in schema:
            return params

        function_schema = schema["function"]
        if "parameters" not in function_schema:
            return params

        parameters = function_schema["parameters"]
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])

        # Determine the single array-typed parameter to auto-correct into,
        # if any. Prefer the schema's `required` list (covers tools that also
        # declare optional properties alongside their one required array,
        # e.g. EditFile's optional `change_id`); fall back to "exactly one
        # property total" when the schema doesn't declare `required` at all.
        single_param_name = None
        if len(required) == 1:
            single_param_name = required[0]
        elif not required and len(properties) == 1:
            single_param_name = next(iter(properties.keys()))

        if single_param_name is not None:
            param_schema = properties.get(single_param_name, {})
            if param_schema.get("type") == "array":
                # Case 1: LLM emitted the array directly (bare list) → wrap
                # it as-is under the expected key, don't nest it again.
                if isinstance(params, list):
                    return {single_param_name: params}
                # Case 2: LLM emitted a single item of the array directly
                # as a dict, missing the expected wrapper key → wrap it.
                if isinstance(params, dict) and single_param_name not in params:
                    return {single_param_name: [params]}

        return params

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_nested(params: dict, path: list[str]) -> tuple[dict | list, str] | None:
        """
        Navigate *params* along *path* and return ``(container, last_key)``.

        Returns ``None`` if any intermediate key is missing or isn't a dict.
        """
        current: dict | list = params
        for key in path[:-1]:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        if isinstance(current, dict):
            return current, path[-1]
        return None

    @staticmethod
    def _set_nested(params: dict, path: list[str], value: object) -> None:
        """Set *value* at the nested location described by *path* in *params*."""
        current = params
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[path[-1]] = value

    @classmethod
    def _apply_validations_to_value(
        cls, params: dict, path: list[str], method_names: list[str]
    ) -> None:
        """Apply the named validations sequentially to the value at *path*."""
        result = cls._get_nested(params, path)
        if result is None:
            return
        container, last_key = result
        if last_key not in container:
            return
        value = container[last_key]

        for method_name in method_names:
            method = getattr(cls, method_name, None)
            if method is None:
                raise ToolError(f"Unknown validation method: {method_name}")
            value = method(value)
            if value is None:
                # Validation chose to drop the value entirely
                container[last_key] = value
                return

        container[last_key] = value

    @classmethod
    def _apply_validations_to_list_items(
        cls, params: dict, path: list[str], method_names: list[str]
    ) -> None:
        """Apply validations to each item of the list found at *path*."""
        result = cls._get_nested(params, path)
        if result is None:
            return
        container, last_key = result
        if last_key not in container:
            return
        items = container[last_key]

        if not isinstance(items, list):
            return

        new_items: list = []
        for item in items:
            for method_name in method_names:
                method = getattr(cls, method_name, None)
                if method is None:
                    raise ToolError(f"Unknown validation method: {method_name}")
                item = method(item)
                if item is None:
                    break
            if item is not None:
                new_items.append(item)

        container[last_key] = new_items

    # ------------------------------------------------------------------
    # Built-in validation methods
    # ------------------------------------------------------------------

    @classmethod
    def coerce_list(cls, item: object) -> list:
        """
        Coerce *item* into a list.

        * If *item* is already a list it is returned as-is (after checking
          for char-split JSON arrays).
        * If *item* is a string it is parsed as JSON.  A JSON array is
          returned directly; a JSON object is wrapped in a list.
        * If *item* is a dict it is wrapped in a list.
        * Otherwise an empty list is returned.
        """
        if isinstance(item, list):
            # Check for per-character-split JSON arrays first
            coerced = responses.try_join_char_split_json_array(item)
            if coerced is not None:
                return coerced
            # Single-element wrapping a JSON string of an array/object
            if len(item) == 1 and isinstance(item[0], str):
                if item[0].strip().startswith(("[", "{", '"')):
                    item = item[0]
                else:
                    return item
            else:
                return item

        if isinstance(item, str):
            text = item.strip()
            if not text:
                return []
            parsed = responses.try_parse_json_value(text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]

            parsed = json_repair.loads(text, skip_json_loads=True)

            if isinstance(parsed, list):
                return parsed

            return []

        if isinstance(item, dict):
            return [item]

        return []

    @classmethod
    def coerce_dict(cls, item: object) -> dict | None:
        """
        Coerce *item* into a dict.

        * If *item* is already a dict it is returned as-is.
        * If *item* is a string it is parsed as JSON; returns the dict if
          successful, otherwise ``None``.
        * All other types return ``None``.
        """
        if isinstance(item, dict):
            return item
        if isinstance(item, str):
            text = item.strip()
            if not text:
                return None
            parsed = responses.try_parse_json_value(text)
            if isinstance(parsed, dict):
                return parsed
            # Fallback: try json repaid json.loads
            try:
                parsed = json_repair.loads(text, skip_json_loads=True)
            except (json.JSONDecodeError, ValueError):
                return None

            if isinstance(parsed, dict):
                return parsed

        return None

    @classmethod
    def coerce_str(cls, item: object) -> str | None:
        """Coerce *item* to a string, returning ``None`` if not possible."""
        if isinstance(item, str):
            return item
        if item is None:
            return None
        try:
            return str(item)
        except (ValueError, TypeError):
            return None

    @classmethod
    def coerce_int(cls, item: object) -> int | None:
        """Coerce *item* to an int, returning ``None`` if not possible."""
        if isinstance(item, int) and not isinstance(item, bool):
            return item
        if isinstance(item, (float, str)):
            try:
                return int(item)
            except (ValueError, TypeError):
                return None
        return None

    @classmethod
    def coerce_bool(cls, item: object) -> bool | None:
        """Coerce *item* to a bool, returning ``None`` if not possible."""
        if isinstance(item, bool):
            return item
        if isinstance(item, str):
            low = item.strip().lower()
            if low in ("true", "1", "yes"):
                return True
            if low in ("false", "0", "no"):
                return False
            return None
        if isinstance(item, int):
            return bool(item)
        return None
