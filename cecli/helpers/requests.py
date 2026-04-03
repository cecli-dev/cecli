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


def _process_thought_signature(container):
    if "provider_specific_fields" not in container:
        container["provider_specific_fields"] = {}

    if not container["provider_specific_fields"]:
        container["provider_specific_fields"] = {}

    psf = container["provider_specific_fields"]

    if "thought_signature" not in psf:
        if "thought_signatures" in psf:
            sigs = psf["thought_signatures"]
            if isinstance(sigs, list) and len(sigs) > 0:
                psf["thought_signature"] = sigs[0]
            elif isinstance(sigs, str):
                psf["thought_signature"] = sigs
            psf.pop("thought_signatures", None)

    if "thought_signature" not in psf:
        psf["thought_signature"] = "skip_thought_signature_validator"


def thought_signature(model, messages):
    # Add thought signatures for Vertex AI and Gemini models
    if model.name.startswith("vertex_ai/") or model.name.startswith("gemini/"):
        for msg in messages:
            # Handle top-level provider_specific_fields
            if "provider_specific_fields" in msg or msg.get("role") == "assistant":
                _process_thought_signature(msg)

            if "tool_calls" in msg:
                tool_calls = msg["tool_calls"]
                if tool_calls:
                    for call in tool_calls:
                        if call:
                            _process_thought_signature(call)

            if "function_call" in msg:
                call = msg["function_call"]
                if call:
                    _process_thought_signature(call)

    return messages


def concatenate_user_messages(messages):
    """Concatenate user messages separated by assistant "(empty response)" messages.

    This function iterates through the messages array, collecting sequences of
    user messages and assistant "(empty response)" messages. All collected user
    messages in a sequence are concatenated into a single user message.

    Args:
        messages: List of message dictionaries

    Returns:
        List of messages with concatenated user messages
    """
    if not messages:
        return messages

    result = []
    user_messages_to_concat = []

    def get_text(c):
        if isinstance(c, str):
            return c
        if isinstance(c, list) and len(c) > 0:
            return c[0].get("text", "") if isinstance(c[0], dict) else str(c[0])
        return str(c)

    def flush_user_messages():
        if user_messages_to_concat:
            concatenated_content = "\n".join(get_text(c) for c in user_messages_to_concat)
            result.append({"role": "user", "content": concatenated_content})
            user_messages_to_concat.clear()

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user" and not isinstance(content, list):
            user_messages_to_concat.append(content)
        elif role == "assistant" and content == "(empty response)":
            continue
        else:
            flush_user_messages()
            result.append(msg)

    flush_user_messages()
    return result


def add_continue_for_no_prefill(model, messages):
    """Add a 'Continue' user message for models that don't support assistant prefill.

    Args:
        model: The model object with info dictionary
        messages: List of message dictionaries

    Returns:
        List of messages with 'Continue' message added if model doesn't support assistant prefill
        and the last message is not already a user message
    """
    # Check if model doesn't support assistant prefill
    # If not, inject a dummy user message with content "Continue"
    # but only if the last message is not already a user message
    if not model.info.get("supports_assistant_prefill", False):
        # Only add "Continue" if the last message is not a user message
        if not messages or messages[-1].get("role") != "user":
            # Add a user message with content "Continue" to the messages list
            messages.append({"role": "user", "content": "Continue"})

    return messages


def model_request_parser(model, messages):
    messages = thought_signature(model, messages)
    messages = remove_empty_tool_calls(messages)
    messages = concatenate_user_messages(messages)
    messages = ensure_alternating_roles(messages)
    messages = add_reasoning_content(messages)
    messages = add_continue_for_no_prefill(model, messages)
    return messages
