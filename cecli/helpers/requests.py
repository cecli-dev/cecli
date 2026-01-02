from ..sendchat import ensure_alternating_roles


def add_reasoning_content(messages):
    """Add empty reasoning content field to assistant messages if not present.

    Args:
        messages: List of message dictionaries

    Returns:
        List of messages with reasoning content added to assistant messages
    """
    for msg in messages:
        if msg.get("role") == "assistant" and "reasoning_content" not in msg:
            msg["reasoning_content"] = ""
    return messages


def remove_empty_tool_calls(messages):
    """Remove messages with tool_calls that are empty arrays.

    Args:
        messages: List of message dictionaries

    Returns:
        List of messages with empty tool_calls messages removed
    """
    return [
        msg
        for msg in messages
        if not (msg.get("role") == "assistant" and "tool_calls" in msg and msg["tool_calls"] == [])
    ]


def thought_signature(model, messages):
    # Add thought signatures for Vertex AI and Gemini models
    if model.name.startswith("vertex_ai/") or model.name.startswith("gemini/"):
        for msg in messages:
            if "tool_calls" in msg:
                tool_calls = msg["tool_calls"]

                if tool_calls:
                    for call in tool_calls:
                        if not call:
                            continue

                        # Check if thought signature is missing in extra_content.google.thought_signature
                        if "provider_specific_fields" not in call:
                            call["provider_specific_fields"] = {}
                        if "thought_signature" not in call["provider_specific_fields"]:
                            call["provider_specific_fields"][
                                "thought_signature"
                            ] = "skip_thought_signature_validator"

            if "function_call" in msg:
                call = msg["function_call"]

                if not call:
                    continue

                # Check if thought signature is missing in extra_content.google.thought_signature
                if "provider_specific_fields" not in call:
                    call["provider_specific_fields"] = {}
                if "thought_signature" not in call["provider_specific_fields"]:
                    call["provider_specific_fields"][
                        "thought_signature"
                    ] = "skip_thought_signature_validator"

    return messages


def model_request_parser(model, messages):
    messages = thought_signature(model, messages)
    messages = remove_empty_tool_calls(messages)
    messages = ensure_alternating_roles(messages)
    messages = add_reasoning_content(messages)
    return messages
