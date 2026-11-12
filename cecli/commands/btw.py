"""``/btw`` — ask a quick side question without tools or conversation pollution."""

from typing import Any, Optional

from cecli.commands.utils.base_command import BaseCommand
from cecli.helpers.asides import add_aside


class BtwCommand(BaseCommand):
    NORM_NAME = "btw"
    DESCRIPTION = "Ask a quick side question without tools or polluting the conversation."

    @classmethod
    async def execute(cls, io, coder, args: str, **kwargs: Any) -> Optional[str]:
        """Send *args* with the full cached chat context and store the raw response."""
        query = (args or "").strip()
        no_context = False

        for flag in ("-n", "--no-context"):
            if query == flag:
                io.tool_error("Usage: /btw [-n|--no-context] <question>")
                return

            if query.startswith(flag + " "):
                no_context = True
                query = query[len(flag) :].strip()
                break

        if not query:
            io.tool_error("Usage: /btw [-n|--no-context] <question>")
            return

        model = getattr(coder, "main_model", None) or getattr(coder, "weak_model", None)

        if model is None:
            io.tool_error("No model is configured for /btw.")
            return

        if no_context:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a concise technical assistant. Answer the user's question "
                        "directly and concisely."
                    ),
                },
                {"role": "user", "content": query},
            ]
        else:
            # Reuse the fully formatted chat context so the request shares the main
            # conversation's prompt prefix and benefits from provider cache hits.
            messages = list(coder.format_chat_chunks())
            messages.append({"role": "user", "content": query})

        try:
            response, _ = await model.simple_send_with_retries(messages)
        except Exception as err:
            io.tool_error(f"Error querying model: {err}")
            return

        text = str(response or "").strip()

        if not text:
            io.tool_error("Model returned an empty response.")
            return

        add_aside(query, text)

        tui_ref = getattr(coder, "tui", None)
        tui = tui_ref() if tui_ref else None

        if tui is None:
            io.tool_output(text)
            return text

        try:
            tui.call_from_thread(tui.open_panel, "asides")
        except Exception:
            io.tool_output(text)

        return text

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the btw command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /btw <question>  # Ask a side question using the full chat context\n"
        help_text += "  /btw -n <question>  # Ask without any chat context\n"
        help_text += "\nThe response is raw text in the TUI's btw panel, which can also be\n"
        help_text += "opened with /open btw. Use the left and right arrows to move through\n"
        help_text += "previous questions and answers.\n"
        return help_text
