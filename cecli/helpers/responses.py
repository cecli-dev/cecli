import json
import re
import time
from typing import List, Optional

from litellm.types.utils import ChatCompletionMessageToolCall, Function

from cecli import utils
from cecli.helpers import nested


def preprocess_json(response: str) -> str:
    # This pattern matches any sequence of backslashes followed by
    # a character or a unicode sequence.
    pattern = r'(\\+)(u[0-9a-fA-F]{4}|["\\\/bfnrt]|.)?'

    def normalize(match):
        suffix = match.group(2) or ""

        # If it's a valid escape character (like \n or \u0020)
        # we ensure it has exactly ONE backslash.
        if re.match(r'^(u[0-9a-fA-F]{4}|["\\\/bfnrt])$', suffix):
            return "\\" + suffix

        # Otherwise, it's a literal backslash (like C:\temp)
        # We ensure it is escaped for JSON (exactly TWO backslashes).
        return "\\\\" + suffix

    return re.sub(pattern, normalize, response)


def extract_tools_from_content_json(content: str) -> Optional[List[ChatCompletionMessageToolCall]]:
    """
    Simple extraction of JSON-like structures that look like tool calls.
    This handles models that write JSON in text instead of using native calling.
    """
    if not content or ("{" not in content and "[" not in content):
        return None

    try:
        json_chunks = utils.split_concatenated_json(content)
        extracted_calls = []
        chunk_index = 0

        for chunk in json_chunks:
            chunk_index += 1
            try:
                json_obj = json.loads(chunk)
                arg_keys = ["arguments", "parameters", "params"]

                if (
                    isinstance(json_obj, dict)
                    and "name" in json_obj
                    and any(key in json_obj for key in arg_keys)
                ):
                    # Create a Pydantic model for the tool call
                    json_args = nested.getter(json_obj, arg_keys)
                    function_obj = Function(
                        name=json_obj["name"],
                        arguments=(
                            json.dumps(json_args)
                            if isinstance(json_args, (dict, list))
                            else str(json_args)
                        ),
                    )
                    tool_call_obj = ChatCompletionMessageToolCall(
                        type="function",
                        function=function_obj,
                        id=f"call_{len(extracted_calls)}_{int(time.time())}_{chunk_index}",
                    )
                    extracted_calls.append(tool_call_obj)
                elif isinstance(json_obj, list):
                    for item in json_obj:
                        if (
                            isinstance(item, dict)
                            and "name" in item
                            and any(key in item for key in arg_keys)
                        ):
                            item_args = nested.getter(item, arg_keys)
                            function_obj = Function(
                                name=item["name"],
                                arguments=(
                                    json.dumps(item_args)
                                    if isinstance(item_args, (dict, list))
                                    else str(item_args)
                                ),
                            )
                            tool_call_obj = ChatCompletionMessageToolCall(
                                type="function",
                                function=function_obj,
                                id=f"call_{len(extracted_calls)}_{int(time.time())}_{chunk_index}",
                            )
                            extracted_calls.append(tool_call_obj)
            except json.JSONDecodeError:
                continue

        return extracted_calls if extracted_calls else None
    except Exception:
        return None


def extract_tools_from_content_xml(content: str) -> Optional[List[ChatCompletionMessageToolCall]]:
    """
    Extraction of Qwen-style XML tool calls.
    Example:
    <function=UpdateTodoList>
    <parameter=tasks>
    [{"task": "Update task list", "done": false, "current": true}]
    </parameter>
    </function>
    """
    if not content or "<function=" not in content:
        return None

    try:
        extracted_calls = []
        # Find all blocks between <function=...> and </function>
        func_blocks = re.finditer(r"<function=(.*?)>(.*?)</function>", content, re.DOTALL)

        for i, block_match in enumerate(func_blocks):
            func_name = block_match.group(1).strip()
            block_content = block_match.group(2).strip()

            params_dict = {}
            param_pattern = r"<parameter=(.*?)>(.*?)</parameter>"
            for param_match in re.finditer(param_pattern, block_content, re.DOTALL):
                key = param_match.group(1).strip()
                value_str = param_match.group(2).strip()
                try:
                    params_dict[key] = json.loads(value_str)
                except json.JSONDecodeError:
                    params_dict[key] = value_str

            function_obj = Function(name=func_name, arguments=json.dumps(params_dict))

            tool_call_obj = ChatCompletionMessageToolCall(
                type="function",
                function=function_obj,
                id=f"xml_call_{i}_{int(time.time())}",
            )
            extracted_calls.append(tool_call_obj)

        return extracted_calls if extracted_calls else None
    except Exception:
        return None


def extract_tools_from_pseudo_json(content: str) -> Optional[List[ChatCompletionMessageToolCall]]:
    """
    Extraction of tool calls from bracket format.

    Handles blocks shaped like:
    [ToolName(arg1=value1, arg2=value2, ...)]

    Where values can be JSON arrays, objects, booleans, strings, or numbers.
    The parser handles nested parentheses and commas inside JSON values.

    Example:
    [Local--ReadRange(show=[{"file_path": "agent.py", "start_text": "class A"}], verbose=true, mode="strict")]
    """
    if not content or "[" not in content:
        return None

    try:
        extracted_calls = []

        # Scan through content to find all [ToolName(...)] blocks
        i = 0
        while i < len(content):
            bracket_start = content.find("[", i)
            if bracket_start == -1:
                break

            # Find the opening paren after the bracket
            paren_start = content.find("(", bracket_start)
            if paren_start == -1:
                i = bracket_start + 1
                continue

            tool_name = content[bracket_start + 1 : paren_start].strip()
            if not tool_name or not re.match(r"^[a-zA-Z0-9_\\-]+$", tool_name):
                i = paren_start + 1
                continue

            # Find matching closing paren tracking nesting depth
            depth = 1
            paren_end = -1
            pos = paren_start + 1
            while pos < len(content) and depth > 0:
                if content[pos] == "(":
                    depth += 1
                elif content[pos] == ")":
                    depth -= 1
                    if depth == 0:
                        paren_end = pos
                        break
                pos += 1

            if paren_end == -1:
                i = paren_start + 1
                continue

            # Expect "]" after ")"
            if paren_end + 1 >= len(content) or content[paren_end + 1] != "]":
                i = paren_end + 1
                continue

            # Extract the payload between the parentheses
            payload = content[paren_start + 1 : paren_end]

            # Parse the arguments from the payload
            args = _parse_bracket_arguments(payload)

            # Create a tool call object
            function_obj = Function(
                name=tool_name,
                arguments=json.dumps(args),
            )
            tool_call_obj = ChatCompletionMessageToolCall(
                type="function",
                function=function_obj,
                id=f"bracket_call_{len(extracted_calls)}_{int(time.time())}",
            )
            extracted_calls.append(tool_call_obj)

            i = paren_end + 2  # Skip past ")]"

        return extracted_calls if extracted_calls else None
    except Exception:
        return None


def prefix_tool_name(server_name: str, tool_name: str) -> str:
    """
    Prefix a tool name with the server name.

    Args:
        server_name: Name of the MCP server
        tool_name: Original tool name

    Returns:
        Prefixed tool name in format "{server_name}--{tool_name}"
    """
    return f"{server_name}--{tool_name}"


def unprefix_tool_name(prefixed_name: str) -> tuple[str, str]:
    """
    Unprefix a tool name that may have a server prefix.

    Args:
        prefixed_name: Tool name that may be prefixed with "{server_name}--{tool_name}"

    Returns:
        Tuple of (server_name, tool_name) where server_name may be empty string
        if no prefix is found
    """
    # Split on the first double dash
    if "--" in prefixed_name:
        # Find the first double dash
        first_dash_index = prefixed_name.find("--")
        server_name = prefixed_name[:first_dash_index]
        tool_name = prefixed_name[first_dash_index + 2 :]  # +2 to skip both dashes
        return server_name, tool_name
    return "", prefixed_name


def prefix_tool_call(tool_call, server_name: str):
    """
    Prefix the function name in a tool call.

    Args:
        tool_call: Tool call (dict or ChatCompletionMessageToolCall) with 'function' key/attribute
        server_name: Name of the MCP server

    Returns:
        New tool call with prefixed function name (same type as input)
    """
    # Handle ChatCompletionMessageToolCall objects
    if hasattr(tool_call, "function") and hasattr(tool_call.function, "name"):
        # Create a copy of the tool call object
        result = ChatCompletionMessageToolCall(
            id=tool_call.id,
            type=tool_call.type,
            function=Function(
                name=prefix_tool_name(server_name, tool_call.function.name),
                arguments=tool_call.function.arguments,
            ),
        )
        return result

    # Handle dictionaries
    if not isinstance(tool_call, dict):
        return tool_call

    # Create a deep copy to avoid modifying the original
    result = tool_call.copy()
    if "function" in result and isinstance(result["function"], dict):
        result["function"] = result["function"].copy()
        if "name" in result["function"]:
            result["function"]["name"] = prefix_tool_name(server_name, result["function"]["name"])

    return result


def unprefix_tool_call(tool_call):
    """
    Unprefix the function name in a tool call.

    Args:
        tool_call: Tool call (dict or ChatCompletionMessageToolCall) with 'function' key/attribute

    Returns:
        Tuple of (server_name, unprefixed_tool_call) where server_name may be empty string
        if no prefix is found (same type as input)
    """
    # Handle ChatCompletionMessageToolCall objects
    if hasattr(tool_call, "function") and hasattr(tool_call.function, "name"):
        server_name, unprefixed_name = unprefix_tool_name(tool_call.function.name)

        # Create a copy of the tool call object with unprefixed name
        result = ChatCompletionMessageToolCall(
            id=tool_call.id,
            type=tool_call.type,
            function=Function(name=unprefixed_name, arguments=tool_call.function.arguments),
        )
        return server_name, result

    # Handle dictionaries
    if not isinstance(tool_call, dict):
        return "", tool_call

    # Create a deep copy to avoid modifying the original
    result = tool_call.copy()
    server_name = ""

    if "function" in result and isinstance(result["function"], dict):
        result["function"] = result["function"].copy()
        if "name" in result["function"]:
            server_name, unprefixed_name = unprefix_tool_name(result["function"]["name"])
            result["function"]["name"] = unprefixed_name

    return server_name, result


def parse_tool_arguments(args_string: str) -> dict:
    """Parse tool-call arguments, merging glued ``{…}{} {…}`` object fragments."""
    text = (args_string or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    parsed = try_parse_json_value(text)
    if isinstance(parsed, dict):
        return parsed

    chunks = utils.split_concatenated_json(text)
    if len(chunks) <= 1:
        if not chunks:
            return {}
        lone = try_parse_json_value(chunks[0])
        if isinstance(lone, dict):
            return lone
        try:
            single = json.loads(chunks[0])
        except json.JSONDecodeError as err:
            return {"@error": f"Malformed JSON arguments: {err}"}
        return single if isinstance(single, dict) else {}

    merged = merge_glued_json_objects(chunks)

    if merged is not None:
        return merged

    return {
        "@error": "Could not merge glued JSON objects: argument fragments are not all JSON objects"
    }


def merge_glued_json_objects(chunks: list[str]) -> dict | None:
    """
    Merge consecutive JSON object strings from glued local-model tool args.

    Example: ``{"limit": 15}{}{"path": "."}`` → ``{"limit": 15, "path": "."}``.
    Returns ``None`` when chunks are not all mergeable objects (caller may split).
    """
    merged: dict = {}
    saw_non_empty = False
    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue
        obj = try_parse_json_value(text)
        if obj is None:
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                return None
        if isinstance(obj, list):
            return None
        if not isinstance(obj, dict):
            return None
        if obj:
            merged.update(obj)
            saw_non_empty = True
    if saw_non_empty or merged == {}:
        return merged
    return None


def try_parse_json_value(text: str):
    """Parse JSON text, including repairs for common local-model tool-arg quirks."""
    text = text.strip()
    if not text:
        return None
    for candidate in (text, _repair_local_model_json_text(text)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    if "}{" in text:
        chunks = utils.split_concatenated_json(text)
        if len(chunks) == 1:
            try:
                return json.loads(chunks[0])
            except json.JSONDecodeError:
                pass
        elif len(chunks) > 1:
            parsed = []
            for chunk in chunks:
                try:
                    parsed.append(json.loads(chunk))
                except json.JSONDecodeError:
                    parsed = None
                    break
            if parsed is not None:
                return parsed
    if len(text) >= 8:
        coerced = try_join_char_split_json_array(list(text))
        if coerced is not None:
            return coerced
    return None


def try_join_char_split_json_array(items: list) -> list | None:
    """
    Some local models emit a JSON array as one string per character in tool args.

    Example: tasks=["[", "{", "\\"", "t", "a", "s", "k", "\\"", ...] instead of
    tasks='[{"task": "...", "done": false}]'.
    """
    if len(items) < 8:
        return None
    # Quick check: the first item must be the opening bracket of a JSON construct.
    # This avoids O(n) string-joining for legitimate string lists like
    # ["file_a.py", "file_b.py", ...] where the first item isn't JSON-like.
    first = items[0]
    if first not in ("[", "{"):
        return None

    if not all(isinstance(x, str) for x in items):
        return None

    joined = "".join(items).strip()
    if not joined.startswith(("[", "{")):
        return None
    try:
        parsed = json.loads(joined)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    return None


def _repair_local_model_json_text(text: str) -> str:
    """
    Repair common local-model breakage in double-encoded tool JSON.

    Models sometimes emit a literal newline between ``:`` and the opening quote
    of a string value (e.g. ``"end_text":\\n",`` instead of ``"end_text": "",``).
    """
    repaired = re.sub(r':\s*\n\s*",', ': "",', text)
    repaired = re.sub(r':\s*\n\s*"}', ': ""}', repaired)
    return repaired


def try_parse_lenient_task_array(text) -> list[dict] | None:
    """
    Parse UpdateTodoList ``tasks`` when the model emits unescaped inner JSON quotes.

    Example::
        [{"done": true, "task": "Explore crates"}, {"done": false, "task": "Review curl"}]
    """
    if isinstance(text, dict):
        if "tasks" in text:
            text = text["tasks"]
        elif "done" in text and "task" in text:
            return [text]
        else:
            return None
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.startswith('"') and raw.endswith('"') and "[{" in raw:
        raw = raw[1:-1]
    if "}{" in raw:
        merged = merge_glued_json_objects(utils.split_concatenated_json(raw))
        if merged and "tasks" in merged:
            raw = str(merged["tasks"])
    if not raw.lstrip().startswith("["):
        return None
    pattern = re.compile(
        r'\{\s*"done"\s*:\s*(true|false)\s*,\s*"task"\s*:\s*"((?:\\.|[^"\\])*)"\s*\}',
        re.IGNORECASE,
    )
    rows = [
        {"done": m.group(1).lower() == "true", "task": m.group(2).replace('\\"', '"')}
        for m in pattern.finditer(raw)
    ]
    return rows if rows else None


def _parse_bracket_arguments(payload_str: str) -> dict:
    """Parse multiple arguments from a bracket-style payload.

    Uses depth-aware scanning instead of regex-based boundary detection,
    so that ``=`` signs nested inside JSON strings, arrays, or objects
    are not mistaken for argument separators.

    Example: ``show=[...], verbose=true, mode="strict"``
    """
    arguments: dict = {}
    i = 0
    n = len(payload_str)

    while i < n:
        # Skip whitespace and inter-argument commas
        while i < n and payload_str[i] in " ,\t":
            i += 1
        if i >= n:
            break

        # Extract key name (alphanumeric, underscore, hyphen)
        key_start = i
        while i < n and (payload_str[i].isalnum() or payload_str[i] in "_-"):
            i += 1
        key = payload_str[key_start:i]

        if not key:
            i += 1
            continue

        # Skip whitespace before '='
        while i < n and payload_str[i] in " \t":
            i += 1
        if i >= n or payload_str[i] != "=":
            i += 1
            continue
        i += 1  # skip '='

        # Skip whitespace before value
        while i < n and payload_str[i] in " \t":
            i += 1

        # Extract value with depth tracking
        value_start = i
        depth_paren = 0  # ()
        depth_brace = 0  # {}
        depth_bracket = 0  # []
        in_dquote = False
        in_squote = False

        while i < n:
            ch = payload_str[i]

            if in_dquote:
                if ch == "\\":
                    i += 2  # skip escaped character
                    continue
                if ch == '"':
                    in_dquote = False
            elif in_squote:
                if ch == "\\":
                    i += 2
                    continue
                if ch == "'":
                    in_squote = False
            else:
                if ch == '"':
                    in_dquote = True
                elif ch == "'":
                    in_squote = True
                elif ch == "(":
                    depth_paren += 1
                elif ch == ")":
                    depth_paren -= 1
                elif ch == "{":
                    depth_brace += 1
                elif ch == "}":
                    depth_brace -= 1
                elif ch == "[":
                    depth_bracket += 1
                elif ch == "]":
                    depth_bracket -= 1
                elif ch == ",":
                    # Comma at depth 0 = next argument separator
                    if depth_paren == 0 and depth_brace == 0 and depth_bracket == 0:
                        break

            i += 1

        val_str = payload_str[value_start:i].strip()
        # Drop trailing comma left by the break
        if val_str.endswith(","):
            val_str = val_str[:-1].strip()

        # Try to parse the value as native JSON
        try:
            arguments[key] = json.loads(val_str)
        except (json.JSONDecodeError, ValueError):
            # Fallback if it is unquoted plain text
            arguments[key] = val_str

    return arguments
