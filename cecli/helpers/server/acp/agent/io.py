"""AcpInputOutput - InputOutput adapter for ``cecli --acp``.

Prompts come from the ACP client instead of a terminal, confirmations become
``session/request_permission`` requests, and output is translated into
``session/update`` notifications by the agent's UpdateEmitter.
"""

from io import StringIO

from rich.console import Console
from rich.text import Text

from cecli.helpers.server.acp.agent import get_agent
from cecli.helpers.server.acp.agent.transport import log
from cecli.helpers.server.acp.agent.updates import strip_ansi
from cecli.io import InputOutput


def _plain(*messages) -> str:
    return strip_ansi(" ".join(m.plain if isinstance(m, Text) else str(m) for m in messages))


class AcpInputOutput(InputOutput):
    def __init__(self, pretty=False, *args, agent=None, **kwargs):
        # Set before InputOutput.__init__, which may already emit warnings
        self.agent = agent or get_agent()
        # Renders the odd Rich object (tables, panels) that reaches stream_print
        self._plain_console = Console(
            file=StringIO(), force_terminal=False, no_color=True, highlight=False, width=200
        )
        kwargs["fancy_input"] = False
        kwargs["notifications"] = False
        kwargs["show_spinner"] = False
        super().__init__(False, *args, **kwargs)
        self.fallback_spinner_enabled = False

    # ── Input ───────────────────────────────────────────────────

    async def get_input(
        self,
        root,
        rel_fnames,
        addable_rel_fnames,
        commands,
        abs_read_only_fnames=None,
        abs_read_only_stubs_fnames=None,
        edit_format=None,
    ):
        self.agent.emitter.root = root
        text = await self.agent.next_input(getattr(commands, "coder", None))
        self.user_input(text)
        return text

    async def _confirm_ask(
        self,
        question,
        default="y",
        subject=None,
        explicit_yes_required=False,
        group=None,
        group_response=None,
        allow_never=False,
        allow_tweak=False,
        acknowledge=False,
        **kwargs,
    ):
        self.num_user_asks += 1
        question_id = (question, subject)

        if question_id in self.never_prompts:
            return False
        if group and not group.show_group:
            group = None
        if group:
            allow_never = True

        if self.yes is True and not explicit_yes_required:
            res = "y"
        elif group_response and group_response in self.group_responses:
            return self.group_responses[group_response]
        elif group and group.preference:
            res = group.preference
        else:
            options = [{"optionId": "y", "name": "Yes", "kind": "allow_once"}]
            if group or group_response:
                if not explicit_yes_required or group_response:
                    options.append({"optionId": "a", "name": "Yes to all", "kind": "allow_always"})
                options.append({"optionId": "s", "name": "Skip all", "kind": "reject_always"})
            options.append({"optionId": "n", "name": "No", "kind": "reject_once"})
            if allow_never and not (group or group_response):
                options.append(
                    {"optionId": "d", "name": "Don't ask again", "kind": "reject_always"}
                )

            choice = await self.agent.ask_permission(
                question, subject, options, agent_uuid=kwargs.get("coder_uuid")
            )
            if choice is None:
                log(f"declined: {question}")
                choice = "n"
            res = choice

        res = res.lower()[0]

        if res == "d" and allow_never:
            self.never_prompts.add(question_id)
            self.append_chat_history(f"{question.strip()} {res}", linebreak=True, blockquote=True)
            return False

        if explicit_yes_required and not group_response:
            is_yes = res == "y"
        else:
            is_yes = res in ("y", "a")

        is_all = res == "a" and (
            (group is not None and not explicit_yes_required) or group_response
        )
        is_skip = res == "s" and (group is not None or group_response)

        if group:
            if is_all and not explicit_yes_required:
                group.preference = "all"
            elif is_skip:
                group.preference = "skip"

        self.append_chat_history(f"{question.strip()} {res}", linebreak=True, blockquote=True)

        if group_response and (is_all or is_skip):
            self.group_responses[group_response] = is_yes

        return is_yes

    def prompt_ask(self, question, default="", subject=None):
        # Free-form answers have no ACP equivalent; take the default
        log(f"using default for prompt: {question} -> {default!r}")
        self.append_chat_history(f"{question.strip()} {default}", linebreak=True, blockquote=True)
        return default

    # ── Output ──────────────────────────────────────────────────

    def tool_output(self, *messages, log_only=False, bold=False, type=None, **kwargs):
        super().tool_output(*messages, log_only=True)
        # The per-request token/cost line stays in the chat history only
        if log_only or type == "usage-report":
            return

        emitter = self.agent.emitter_for(kwargs.get("coder_uuid"))
        if type == "Tool Call":
            emitter.tool_header(_plain(*messages))
        elif type == "tool-footer":
            emitter.tool_footer()
        elif messages:
            emitter.block(_plain(*messages))

    def _tool_message(self, message="", strip=True, color=None, **kwargs):
        if message.strip():
            if "\n" in message:
                for line in message.splitlines():
                    self.append_chat_history(line, linebreak=True, blockquote=True, strip=strip)
            else:
                hist = message.strip() if strip else message
                self.append_chat_history(hist, linebreak=True, blockquote=True)
        self.agent.emitter_for(kwargs.get("coder_uuid")).block(_plain(message))

    def assistant_output(self, message, pretty=None, **kwargs):
        emitter = self.agent.emitter_for(kwargs.get("coder_uuid"))
        emitter.stream(_plain(message or ""), final=True)

    def stream_output(self, text, final=False, **kwargs):
        emitter = self.agent.emitter_for(kwargs.get("coder_uuid"))
        emitter.stream(strip_ansi(text or ""), final=final)

    def reset_streaming_response(self, **kwargs):
        pass

    def stream_print(self, *messages, **kwargs):
        console = self._plain_console
        with console.capture() as capture:
            console.print(*messages, markup=False, soft_wrap=True)
        self.agent.emitter_for(kwargs.get("coder_uuid")).block(strip_ansi(capture.get()))

    def tool_call_event(self, tool_call_id, status, coder_uuid=None, **kwargs):
        self.agent.emitter_for(coder_uuid).tool_event(tool_call_id, status, **kwargs)

    def subagent_event(self, agent_uuid, event, **kwargs):
        self.agent.subagent_event(agent_uuid, event, **kwargs)

    def display_user_input(self, inp):
        # The client already shows what the user sent
        pass

    # ── Terminal-only behavior ──────────────────────────────────

    def rule(self):
        pass

    def ring_bell(self, **kwargs):
        pass

    def notify_user_input_required(self, **kwargs):
        pass
