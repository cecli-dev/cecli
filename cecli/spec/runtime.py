"""Protocols for Vision HTTP session glue (implemented in bright_vision_core)."""

from __future__ import annotations

from typing import Any, Iterator, Protocol


class SpecTurnRunner(Protocol):
    """Headless chat session used for repo-grounded spec generation."""

    def apply_spec_gen_route(self, routing_text: str) -> None:
        """Apply model-router tier hint for spec-generation turns."""
        ...

    def run_message(self, message: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Stream one user turn as Vision SSE-shaped event dicts."""
        ...

    def run_one_shot(
        self,
        message: str,
        *,
        timeout_s: float,
        **kwargs: Any,
    ) -> str:
        """Run a single turn and return assistant text (no streaming)."""
        ...

    def interrupt_turn(self) -> None:
        """Cancel the in-flight turn, if any."""
        ...


class AgentCoderBridge(Protocol):
    @property
    def root(self) -> Any:
        """Workspace root path object."""
        ...

    def local_agent_folder(self, name: str) -> str:
        """Resolve ``.cecli/agents/<name>/`` under the workspace."""
        ...


class AgentTodoSession(Protocol):
    @property
    def coder(self) -> AgentCoderBridge:
        """Active agent coder for workspace file access."""
        ...
