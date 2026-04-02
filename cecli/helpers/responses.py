import json
import re
import time
from typing import List, Optional

from litellm.types.utils import ChatCompletionMessageToolCall, Function

from cecli import utils


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
                if isinstance(json_obj, dict) and "name" in json_obj and "arguments" in json_obj:
                    # Create a Pydantic model for the tool call
                    function_obj = Function(
                        name=json_obj["name"],
                        arguments=(
                            json.dumps(json_obj["arguments"])
                            if isinstance(json_obj["arguments"], (dict, list))
                            else str(json_obj["arguments"])
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
                        if isinstance(item, dict) and "name" in item and "arguments" in item:
                            function_obj = Function(
                                name=item["name"],
                                arguments=(
                                    json.dumps(item["arguments"])
                                    if isinstance(item["arguments"], (dict, list))
                                    else str(item["arguments"])
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
