import hashlib
import json
import math
import time
import uuid

from cecli.exceptions import LiteLLMExceptions
from cecli.llm import litellm

from .base_coder import Coder


class CopyPasteCoder(Coder):
    """Coder implementation that performs clipboard-driven interactions.

    This coder swaps the transport mechanism (clipboard vs API) but must remain compatible with the
    base ``Coder`` interface. In particular, many base methods assume ``self.gpt_prompts`` exists.

    We therefore mirror the prompt pack from the coder that matches the currently selected
    ``edit_format``.
    """

    # CopyPasteCoder doesn't have its own prompt format - it dynamically determines
    # prompts based on the selected edit_format
    prompt_format = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Ensure CopyPasteCoder always has a prompt pack.
        # We mirror prompts from the coder that matches the active edit format.
        self._init_prompts_from_selected_edit_format()

    @property
    def gpt_prompts(self):
        """Override gpt_prompts property for CopyPasteCoder.

        CopyPasteCoder dynamically determines prompts based on the selected edit format.
        This property returns the prompts that were set by _init_prompts_from_selected_edit_format().
        """
        if not hasattr(self, "_gpt_prompts"):
            raise AttributeError(
                "CopyPasteCoder must call _init_prompts_from_selected_edit_format() "
                "before accessing gpt_prompts"
            )
        return self._gpt_prompts

    @gpt_prompts.setter
    def gpt_prompts(self, value):
        """Setter for gpt_prompts property."""
        self._gpt_prompts = value

    def _init_prompts_from_selected_edit_format(self):
        """Initialize ``self.gpt_prompts`` based on the currently selected edit format.

        This prevents AttributeError crashes when base ``Coder`` code assumes ``self.gpt_prompts``
        exists (eg during message formatting, announcements, cancellation/cleanup paths, etc).
        """
        # Determine the selected edit_format the same way Coder.create() does.
        selected_edit_format = None
        if getattr(self, "args", None) is not None and getattr(self.args, "edit_format", None):
            selected_edit_format = self.args.edit_format
        else:
            selected_edit_format = getattr(self.main_model, "edit_format", None)

        # "code" is treated like None in Coder.create()
        if selected_edit_format == "code":
            selected_edit_format = None

        # If no edit format is selected, fall back to model default.
        if selected_edit_format is None:
            selected_edit_format = getattr(self.main_model, "edit_format", None)

        # Find the coder class that would have been selected for this edit_format.
        try:
            import cecli.coders as coders
        except Exception:
            coders = None

        target_coder_class = None
        if coders is not None:
            for coder_cls in getattr(coders, "__all__", []):
                if (
                    hasattr(coder_cls, "edit_format")
                    and coder_cls.edit_format == selected_edit_format
                ):
                    target_coder_class = coder_cls
                    break

        # Mirror prompt pack + edit_format where available.
        if target_coder_class is not None:
            # All coder classes must have prompt_format attribute
            if (
                not hasattr(target_coder_class, "prompt_format")
                or target_coder_class.prompt_format is None
            ):
                raise AttributeError(
                    f"Target coder class {target_coder_class.__name__} must have a 'prompt_format'"
                    " attribute."
                )

            prompt_name = target_coder_class.prompt_format

            # Get prompts from cache or load them
            if prompt_name in Coder._prompt_cache:
                self.gpt_prompts = Coder._prompt_cache[prompt_name]
            else:
                # Create a dummy instance to trigger prompt loading
                dummy_instance = target_coder_class.__new__(target_coder_class)
                dummy_instance.__class__ = target_coder_class
                self.gpt_prompts = dummy_instance.gpt_prompts

            # Keep announcements/formatting consistent with the selected coder.
            self.edit_format = getattr(target_coder_class, "edit_format", self.edit_format)
            return

        # Last-resort fallback: avoid crashing if we can't determine the prompts.
        # Prefer keeping any existing gpt_prompts (if one was set elsewhere).
        if not hasattr(self, "_gpt_prompts"):
            self.gpt_prompts = None

    async def send(self, messages, model=None, functions=None, tools=None):
        model = model or self.main_model

        if getattr(model, "copy_paste_transport", "api") == "api":
            async for chunk in super().send(
                messages, model=model, functions=functions, tools=tools
            ):
                yield chunk
            return

        if functions:
            self.io.tool_warning("copy/paste mode ignores function call requests.")
        if tools:
            self.io.tool_warning("copy/paste mode ignores tool call requests.")

        self.io.reset_streaming_response()

        # Base Coder methods (eg show_send_output/preprocess_response) expect these streaming
        # attributes to always exist, even when we bypass the normal API streaming path.
        self.partial_response_content = ""
        self.partial_response_function_call = None
        # preprocess_response() does len(self.partial_response_tool_calls), so it must not be None.
        self.partial_response_tool_calls = []

        try:
            hash_object, completion = self.copy_paste_completion(messages, model)
            self.chat_completion_call_hashes.append(hash_object.hexdigest())
            self.show_send_output(completion)
            self.calculate_and_show_tokens_and_cost(messages, completion)
        finally:
            self.preprocess_response()

            if self.partial_response_content:
                self.io.ai_output(self.partial_response_content)

    def copy_paste_completion(self, messages, model):
        try:
            from cecli.helpers import copypaste
        except ImportError:  # pragma: no cover - import error path
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

        try:
            copypaste.copy_to_clipboard(prompt_text)
        except copypaste.ClipboardError as err:  # pragma: no cover - clipboard error path
            self.io.tool_error(f"Unable to copy prompt to clipboard: {err}")
            raise

        self.io.tool_output("Request copied to clipboard.")
        self.io.tool_output("Paste it into your LLM interface, then copy the reply back.")
        self.io.tool_output("Waiting for clipboard updates (Ctrl+C to cancel)...")

        try:
            last_value = copypaste.read_clipboard()
        except copypaste.ClipboardError as err:  # pragma: no cover - clipboard error path
            self.io.tool_error(f"Unable to read clipboard: {err}")
            raise

        try:
            response_text = copypaste.wait_for_clipboard_change(initial=last_value)
        except copypaste.ClipboardError as err:  # pragma: no cover - clipboard error path
            self.io.tool_error(f"Unable to read clipboard: {err}")
            raise

        # Estimate tokens locally using the model's tokenizer; fallback to heuristic.
        def _safe_token_count(text):
            """Return token count via the model tokenizer, falling back to a heuristic."""
            if not text:
                return 0
            try:
                count = model.token_count(text)
                if isinstance(count, int) and count >= 0:
                    return count
            except Exception as ex:
                # Try to map known LiteLLM exceptions to user-friendly messages, then fall back.
                try:
                    ex_info = LiteLLMExceptions().get_ex_info(ex)
                    if ex_info and ex_info.description:
                        self.io.tool_warning(
                            f"Token count failed: {ex_info.description} Falling back to heuristic."
                        )
                except Exception:
                    # Avoid masking the original issue during error mapping.
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
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        )

        kwargs = dict(model=model.name, messages=messages, stream=False)
        hash_object = hashlib.sha1(json.dumps(kwargs, sort_keys=True).encode())  # nosec B324
        return hash_object, completion
