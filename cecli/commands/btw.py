from __future__ import annotations

from typing import Any, Dict, List, Optional

from cecli.commands.utils.base_command import BaseCommand
from cecli.helpers.conversation import ConversationService, MessageTag


class BtwCommand(BaseCommand):
    NORM_NAME = "btw"
    DESCRIPTION = (
        "Ask a quick side-question without polluting conversation history or running tools. "
        "Usage: /btw [-n|--no-context] <question>"
    )

    @classmethod
    def _extract_recent_turns(cls, coder, max_turns: int = 4) -> List[Dict[str, str]]:
        """Extract up to max_turns recent user/assistant turns without heavy payloads."""
        manager = ConversationService.get_manager(coder)
        done = manager.get_messages_dict(MessageTag.DONE) or []
        cur = manager.get_messages_dict(MessageTag.CUR) or []
        combined = list(done) + list(cur)

        filtered: List[Dict[str, str]] = []
        for msg in combined:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content")
            if not content or not isinstance(content, str):
                continue

            # Skip large injected system messages or file dumps
            if content.startswith(("Original File Contents For:", "Current File Contents For:")):
                continue

            # Truncate any long message to keep side-channel lightweight
            snippet = content.strip()
            if len(snippet) > 500:
                snippet = snippet[:500] + "..."

            filtered.append({"role": role, "content": snippet})

        return filtered[-max_turns:]

    @classmethod
    def _build_context_system_prompt(cls, coder) -> str:
        """Build a concise, low-token context string for the side query."""
        parts = [
            "You are a concise technical assistant answering a quick side-question ('by the way') "
            "for a developer working in a terminal coding session.",
            "Rules:",
            "- Answer directly and concisely using clean Markdown.",
            "- Do NOT attempt to run tools, write files, or generate tool call tags.",
            "- Focus only on answering the developer's question.",
        ]

        # Working directory & branch
        root = getattr(coder, "root", None)
        if root:
            parts.append(f"Workspace root: {root}")

        repo = getattr(coder, "repo", None)
        if repo and hasattr(repo, "get_head_name"):
            try:
                branch = repo.get_head_name()
                if branch:
                    parts.append(f"Git branch: {branch}")
            except Exception:
                pass

        # Files currently in chat / editable context
        in_chat = sorted(coder.get_inchat_relative_files() if hasattr(coder, "get_inchat_relative_files") else [])
        if in_chat:
            files_str = ", ".join(in_chat[:15])
            if len(in_chat) > 15:
                files_str += f" (+{len(in_chat) - 15} more)"
            parts.append(f"Files currently in context: {files_str}")

        return "\n".join(parts)

    @classmethod
    async def execute(cls, io, coder, args: str, **kwargs: Any) -> Optional[str]:
        raw_query = (args or "").strip()
        if not raw_query:
            io.tool_error("Please provide a question. Usage: /btw [-n|--no-context] <question>")
            return "Usage: /btw [-n|--no-context] <question>"

        no_context = False
        query = raw_query

        # Check for -n / --no-context flags
        if query.startswith("-n "):
            no_context = True
            query = query[3:].strip()
        elif query.startswith("--no-context "):
            no_context = True
            query = query[13:].strip()
        elif query in ("-n", "--no-context"):
            io.tool_error("Please provide a question after the flag. Usage: /btw [-n|--no-context] <question>")
            return "Usage: /btw [-n|--no-context] <question>"

        if not query:
            io.tool_error("Please provide a question. Usage: /btw [-n|--no-context] <question>")
            return "Usage: /btw [-n|--no-context] <question>"

        # Use coder's main model, or weak_model if main is missing
        model = getattr(coder, "main_model", None) or getattr(coder, "weak_model", None)
        if not model:
            io.tool_error("No model is configured for /btw query.")
            return "Error: No model configured"

        # Build message chain
        messages: List[Dict[str, str]] = []

        if no_context:
            messages.append({
                "role": "system",
                "content": (
                    "You are a helpful and concise technical assistant. "
                    "Answer the user's question directly and concisely using clean Markdown."
                ),
            })
        else:
            system_prompt = cls._build_context_system_prompt(coder)
            messages.append({"role": "system", "content": system_prompt})

            # Add recent turns for conversational continuity
            recent_turns = cls._extract_recent_turns(coder, max_turns=4)
            messages.extend(recent_turns)

        # Final user side-question
        messages.append({"role": "user", "content": query})

        try:
            # Query model directly without adding to conversation manager
            response, _ = await model.simple_send_with_retries(messages)
            if not response or not str(response).strip():
                io.tool_error("Model returned an empty response.")
                return "Error: Empty response"

            response_text = str(response).strip()

            mode_tag = "(isolated)" if no_context else "(context-aware)"
            header = f"💬 /btw: {query} {mode_tag}"
            io.tool_output(header)

            # Route through assistant_output so both CLI and Textual TUI
            # format the response natively as formatted Markdown without breaking
            coder_uuid = getattr(coder, "uuid", None)
            io.assistant_output(response_text, coder_uuid=coder_uuid)

            return "Successfully executed /btw."

        except Exception as e:
            io.tool_error(f"Error querying model: {str(e)}")
            return f"Error: {str(e)}"

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /btw <question>                # Ask a question with lightweight project/chat context\n"
        help_text += "  /btw -n <question>             # Ask an isolated question without any context\n"
        help_text += "  /btw --no-context <question>   # Same as -n\n"
        help_text += "\nExamples:\n"
        help_text += "  /btw what does this regex mean? [a-z0-9_]+\n"
        help_text += "  /btw what is the difference between git rebase and merge?\n"
        help_text += "  /btw -n write a quick powershell one-liner to find large files\n"
        help_text += "\nNote: /btw queries run outside the main conversation loop. They do NOT\n"
        help_text += "modify files, trigger tools, or pollute your chat token history.\n"
        return help_text
