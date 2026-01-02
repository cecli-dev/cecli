from dataclasses import dataclass, field
from typing import List


@dataclass
class ChatChunks:
    system: List = field(default_factory=list)
    static: List = field(default_factory=list)
    examples: List = field(default_factory=list)
    pre_message: List = field(default_factory=list)
    done: List = field(default_factory=list)
    repo: List = field(default_factory=list)
    readonly_files: List = field(default_factory=list)
    chat_files: List = field(default_factory=list)
    edit_files: List = field(default_factory=list)
    cur: List = field(default_factory=list)
    post_message: List = field(default_factory=list)
    reminder: List = field(default_factory=list)
    chunk_ordering: List = field(default_factory=list)

    def __init__(self, chunk_ordering=None):
        self.chunk_ordering = chunk_ordering

    def all_messages(self):
        if self.chunk_ordering:
            messages = []
            for chunk_name in self.chunk_ordering:
                chunk = getattr(self, chunk_name, [])
                if chunk:
                    messages.extend(chunk)
            return messages
        else:
            return (
                self.format_list("system")
                + self.format_list("static")
                + self.format_list("examples")
                + self.format_list("readonly_files")
                + self.format_list("chat_files")
                + self.format_list("repo")
                + self.format_list("pre_message")
                + self.format_list("done")
                + self.format_list("edit_files")
                + self.format_list("cur")
                + self.format_list("post_message")
                + self.format_list("reminder")
            )

    def add_cache_control_headers(self):
        # Limit to 4 cacheable blocks to appease Anthropic's limits on chunk caching
        if self.format_list("readonly_files"):
            self.add_cache_control(self.format_list("readonly_files"))
        elif self.format_list("static"):
            self.add_cache_control(self.format_list("static"))
        elif self.format_list("examples"):
            self.add_cache_control(self.format_list("examples"))
        else:
            self.add_cache_control(self.format_list("system"))

        # The files form a cacheable block.
        # The block starts with readonly_files and ends with chat_files.
        # So we mark the end of chat_files.
        # self.add_cache_control(self.add_cache_control(self.format_list("chat_files"))

        # The repo map is its own cacheable block.
        if self.format_list("repo"):
            self.add_cache_control(self.format_list("repo"))
        elif self.format_list("chat_files"):
            self.add_cache_control(self.format_list("chat_files"))

        # The history is ephemeral on its own.
        self.add_cache_control(self.add_cache_control(self.format_list("cur")), penultimate=True)

    # Per this: https://github.com/BerriAI/litellm/issues/10226
    # The first and second to last messages are cache optimal
    # Since caches are also written to incrementally and you need
    # the past and current states to properly append and gain
    # efficiencies/savings in cache writing
    def add_cache_control(self, messages, penultimate=False):
        if not messages:
            return

        if penultimate and len(messages) < 2:
            content = messages[-2]["content"]
            if type(content) is str:
                content = dict(
                    type="text",
                    text=content,
                )
            content["cache_control"] = {"type": "ephemeral"}

            messages[-2]["content"] = [content]

        content = messages[-1]["content"]
        if type(content) is str:
            content = dict(
                type="text",
                text=content,
            )
        content["cache_control"] = {"type": "ephemeral"}

        messages[-1]["content"] = [content]

    def cacheable_messages(self):
        messages = self.all_messages()
        for i, message in enumerate(reversed(messages)):
            if isinstance(message.get("content"), list) and message["content"][0].get(
                "cache_control"
            ):
                return messages[: len(messages) - i]
        return messages

    def format_list(self, chunk):
        if type(getattr(self, chunk, [])) is not list:
            return []

        return getattr(self, chunk, [])
