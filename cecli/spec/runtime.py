"""Protocols for Vision HTTP session glue (implemented in bright_vision_core)."""

from __future__ import annotations

from typing import Any, Iterator, Protocol


class SpecTurnRunner(Protocol):
    """Headless chat session used for repo-grounded spec generation."""

    def apply_spec_gen_route(self, routing_text: str) -> None: ...

    def run_message(self, message: str, **kwargs: Any) -> Iterator[dict[str, Any]]: ...

    def run_one_shot(
        self,
        message: str,
        *,
        timeout_s: float,
        **kwargs: Any,
    ) -> str: ...

    def interrupt_turn(self) -> None: ...


class AgentCoderBridge(Protocol):
    @property
    def root(self) -> Any: ...

    def local_agent_folder(self, name: str) -> str: ...


class AgentTodoSession(Protocol):
    @property
    def coder(self) -> AgentCoderBridge: ...
