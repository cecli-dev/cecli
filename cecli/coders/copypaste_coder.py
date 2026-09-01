import hashlib
import json
import math
import time
import uuid

from cecli.exceptions import LiteLLMExceptions
from cecli.llm import litellm

from .base_coder import Coder, EmptyResponseError


class CopyPasteCoder(Coder):
    """Fixed marker class for isinstance checks and backward compatibility.

    When ``copy_paste_mode`` is active, instantiating this class automatically
    returns an instance of a dynamic subclass that inherits from **both** this
    class and the coder matching the selected ``edit_format`` (e.g.
    ``AgentCoder``, ``EditBlockCoder``, ``AskCoder``, …).  The dynamic subclass
    overrides ``send()`` with the clipboard-transport logic while inheriting
    all other behaviour from the target coder.

    This fixed class exists only so that ``isinstance(coder, CopyPasteCoder)``
    works and the name remains importable from ``cecli.coders``.
    """

    # CopyPasteCoder doesn't have its own prompt format.
    prompt_format = None

    def __new__(cls, *args, **kwargs):
        """Intercept instantiation to return a dynamic subclass instance.

        When ``CopyPasteCoder()`` is called, this creates a dynamic subclass
        that inherits from **both** ``CopyPasteCoder`` (for isinstance checks)
        and the coder class matching the selected ``edit_format``.

        Python will automatically call ``__init__`` on the returned instance
        because ``isinstance(result, CopyPasteCoder)`` is ``True``.
        """
        # If already instantiating a dynamic subclass, create normally
        if cls is not CopyPasteCoder:
            return super().__new__(cls)

        # --- resolve the effective edit format -------------------------------
        main_model = args[0] if args else None
        args_obj = kwargs.get("args")
        edit_format = None
        if args_obj is not None:
            edit_format = getattr(args_obj, "edit_format", None)
        if not edit_format or edit_format == "code":
            edit_format = getattr(main_model, "edit_format", None)

        # --- delegate to the factory function --------------------------------
        dynamic_cls = get_copy_paste_coder_class(edit_format, main_model)
        return object.__new__(dynamic_cls)

    prompt_format = None


def get_copy_paste_coder_class(edit_format, main_model):
    """Dynamically create a CopyPasteCoder class that inherits from the
    coder class matching the selected ``edit_format``.

    ``CopyPasteCoder`` is a transport-layer wrapper: it swaps the API
    transport for clipboard transport while inheriting all behavioural
    traits (editing, prompting, announcements, …) from the target coder
    class (e.g. ``AgentCoder``, ``EditBlockCoder``, ``AskCoder``, …).
    """
    import cecli.coders as coders

    # --- resolve the effective edit format -----------------------------------
    effective_format = edit_format
    if not effective_format or effective_format == "code":
        effective_format = getattr(main_model, "edit_format", None)

    # --- find the target base class ------------------------------------------
    if effective_format:
        coder_name = coders.EDIT_FORMAT_MAP.get(effective_format)
        base_class = getattr(coders, coder_name, Coder) if coder_name else Coder
    else:
        base_class = Coder

    # ---- create the dynamic class first so methods can reference it -----
    # Use a different local variable name to avoid shadowing the
    # module-level CopyPasteCoder (needed for the bases tuple).
    DynamicCopyPasteCoder = type(
        "CopyPasteCoder",
        (CopyPasteCoder, base_class),
        {
            "__module__": __name__,
            "prompt_format": getattr(base_class, "prompt_format", None),
        },
    )

    # ---- clipboard-specific transport method --------------------------------
    async def send(self, messages, model=None, functions=None, tools=None):
        model = model or self.main_model

        if getattr(model, "copy_paste_transport", "api") == "api":
            # Fall through to the base coder's normal send()
            async for chunk in base_class.send(
                self, messages, model=model, functions=functions, tools=tools
            ):
                yield chunk
            return

        self.interrupt_event.clear()
        self.got_reasoning_content = False
        self.ended_reasoning_content = False
        self.empty_response = False

        self._streaming_buffer_length = 0
        self.io.reset_streaming_response()

        # Base Coder methods (eg show_send_output/preprocess_response) expect these
        # streaming attributes to always exist, even when we bypass the normal API
        # streaming path.
        self.partial_response_content = ""
        self.partial_response_reasoning_content = ""
        self.partial_response_chunks = []
        self.partial_response_tool_calls = []
        self.partial_response_function_call = dict()
        # preprocess_response() does len(self.partial_response_tool_calls),
        # so it must not be None.
        self.partial_response_consolidated = None

        try:
            hash_object, completion = self.copy_paste_completion(messages, model)
            self.chat_completion_call_hashes.append(hash_object.hexdigest())
            await self.show_send_output(completion)

            if self.empty_response:
                raise EmptyResponseError

            response, func_err, content_err = self.consolidate_chunks()
            if response:
                completion = response
            self.calculate_and_show_tokens_and_cost(messages, completion)
        finally:
            self.preprocess_response()

            if self.partial_response_content:
                self.io.ai_output(self.partial_response_content)

    # ---- clipboard completion logic ------------------------------------------
    def copy_paste_completion(self, messages, model):

        try:
            from cecli.helpers import copypaste
        except ImportError:
            self.io.tool_error("copy/paste mode requires the pyperclip package.")
            self.io.tool_output("Install it with: pip install pyperclip")
            raise

        def content_to_text(content):
            """Extract text from the various content formats cecli/LLMs can produce."""
            if not content:
                return ""
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                    elif isinstance(part, str):
                        parts.append(part)
                return "".join(parts)
            if isinstance(content, dict):
                text = content.get("text")
                if isinstance(text, str):
                    return text
                return ""
            return str(content)

        lines = []
        for message in messages:
            text_content = content_to_text(message.get("content"))
            if not text_content:
                continue
            role = message.get("role")
            if role:
                lines.append(f"{role.upper()}:\n{text_content}")
            else:
                lines.append(text_content)

        prompt_text = "\n\n".join(lines).strip()

        # --- incremental context: strip previously-sent exchange ---
        last_prompt = getattr(self, "_last_prompt_text", None)
        last_response = getattr(self, "_last_response_text", None)
        _full_prompt = prompt_text  # Keep the original for storage
        if last_prompt is not None and last_response is not None:
            expected_prefix = f"{last_prompt}\n\nASSISTANT:\n{last_response}"
            if prompt_text.startswith(expected_prefix):
                new_only = prompt_text[len(expected_prefix) :].strip()
                if new_only:
                    prompt_text = new_only

        self._last_prompt_text = _full_prompt

        try:
            copypaste.copy_to_clipboard(prompt_text)
        except copypaste.ClipboardError as err:
            self.io.tool_error(f"Unable to copy prompt to clipboard: {err}")
            raise

        self.io.tool_output("Request copied to clipboard.")
        self.io.tool_output("Paste it into your LLM interface, then copy the reply back.")
        self.io.tool_output("Waiting for clipboard updates (Ctrl+C to cancel)...")

        try:
            last_value = copypaste.read_clipboard()
        except copypaste.ClipboardError as err:
            self.io.tool_error(f"Unable to read clipboard: {err}")
            raise

        try:
            response_text = copypaste.wait_for_clipboard_change(initial=last_value)
        except copypaste.ClipboardError as err:
            self.io.tool_error(f"Unable to read clipboard: {err}")
            raise

        self._last_response_text = response_text

        def _safe_token_count(text):
            """Return token count via the model tokenizer, falling back to a heuristic."""
            if not text:
                return 0
            try:
                count = model.token_count(text)
                if isinstance(count, int) and count >= 0:
                    return count
            except Exception as ex:
                try:
                    ex_info = LiteLLMExceptions().get_ex_info(ex)
                    if ex_info and ex_info.description:
                        self.io.tool_warning(
                            f"Token count failed: {ex_info.description} Falling back to heuristic."
                        )
                except Exception:
                    pass
            return int(math.ceil(len(text) / 4))

        prompt_tokens = _safe_token_count(prompt_text)
        completion_tokens = _safe_token_count(response_text)
        total_tokens = prompt_tokens + completion_tokens

        completion = litellm.ModelResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            choices=[
                litellm.Choices(
                    index=0,
                    finish_reason="stop",
                    message=litellm.Message(role="assistant", content=response_text),
                )
            ],
            created=int(time.time()),
            model=model.name,
            usage=litellm.Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
        )

        kwargs = dict(model=model.name, messages=messages, stream=False)
        hash_object = hashlib.sha1(json.dumps(kwargs, sort_keys=True).encode())
        return hash_object, completion

    # ---- attach the clipboard methods and return -----------------------------
    DynamicCopyPasteCoder.send = send
    DynamicCopyPasteCoder.copy_paste_completion = copy_paste_completion
    return DynamicCopyPasteCoder
