import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import xxhash

from cecli.helpers.key_detection import redact_api_keys


@dataclass
class BaseMessage:
    """
    Represents an individual message in the conversation stream with metadata
    for ordering and lifecycle management.

    Attributes:
        message_dict: The actual message content (dict with at least "role" and "content" keys)
        message_id: Unique hash ID generated from role and content
        tag: Message type (matching chunk types)
        priority: Integer determining placement in stream (lower = earlier)
        timestamp: Creation timestamp in nanoseconds
        mark_for_delete: Optional integer countdown for deletion (None = permanent)
        hash_key: Optional tuple for custom hash generation
    """

    message_dict: Dict[str, Any]
    tag: str
    priority: int = field(default=0)
    timestamp: int = field(default_factory=lambda: time.monotonic_ns())
    mark_for_delete: Optional[int] = field(default=None)
    mark_for_demotion: Optional[int] = field(default=None)
    promotion: Optional[int] = field(default=None)
    hash_key: Optional[Tuple[str, ...]] = field(default=None)
    message_id: Optional[str] = field(default=None)

    def __post_init__(self):
        """Generate message ID after initialization.

        ``message_dict`` has already been through the redaction choke point in
        ``__setattr__``, so the id hashes the redacted content.
        """
        if self.message_id is None:
            self.message_id = self.generate_id()

        # Validate message structure
        if "role" not in self.message_dict:
            raise ValueError("Message dict must contain 'role' key")
        if "content" not in self.message_dict and not self.message_dict.get("tool_calls"):
            raise ValueError("Message dict must contain 'content' key or 'tool_calls'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Enforce the secret boundary on every write of the message content.

        Assigning ``message_dict`` is the only way content enters a message,
        both at construction and when the conversation manager force-updates an
        existing one, so registered api keys are stripped here and never reach
        the stored dict (or anything that later reads it: logs, sessions).
        """
        if name == "message_dict":
            value = redact_api_keys(value)

        super().__setattr__(name, value)

    def _transform_message(self, tool_calls):
        """Helper method to transform tool_calls, calling to_dict() on objects if needed."""
        if not tool_calls:
            return tool_calls

        # Handle both dicts and objects with to_dict() method
        tool_calls_list = []
        for tool_call in tool_calls:
            if hasattr(tool_call, "to_dict"):
                tool_calls_list.append(tool_call.to_dict())
            else:
                tool_calls_list.append(tool_call)
        return tool_calls_list

    def _serialize_default(self, content):
        return "<not serializable>"

    def generate_id(self) -> str:
        """
        Creates deterministic hash from hash_key or (role, content).
        For messages with role "tool", generates a completely random hash
        so tool calls always have unique responses.

        Returns:
            MD5 hash string for message identification
        """
        # Check if this is a tool response message
        role = self.message_dict.get("role", "")
        if role == "tool":
            # Generate a completely random UUID for tool responses
            # This ensures tool calls always have unique responses even with identical content
            return str(uuid.uuid4())

        if self.hash_key:
            # Use custom hash key if provided
            key_data = "".join(str(item) for item in self.hash_key)
        else:
            # Default: hash based on role and content
            content = self.message_dict.get("content", "")
            tool_calls = self.message_dict.get("tool_calls")

            if tool_calls:
                # For tool calls, include them in the hash
                transformed_tool_calls = self._transform_message(tool_calls)
                tool_calls_str = json.dumps(transformed_tool_calls, default=self._serialize_default)
                key_data = f"{role}:{content}:{tool_calls_str}"
            else:
                key_data = f"{role}:{content}"

        # Use xxhash for fast, deterministic, content-based identification
        return xxhash.xxh3_128_hexdigest(key_data.encode("utf-8"))

    def to_dict(self) -> Dict[str, Any]:
        """
        Returns message_dict for LLM consumption.

        Returns:
            The message dictionary with tool_calls serialized and any
            registered api keys replaced by <redacted>
        """
        # Return a copy to avoid modifying the original
        result = dict(self.message_dict)

        # Handle tool_calls transformation if present
        if "tool_calls" in result and result["tool_calls"]:
            result["tool_calls"] = self._transform_message(result["tool_calls"])

        # Second pass for keys registered after this message was created
        return redact_api_keys(result)

    def is_promoted(self) -> bool:
        """
        Returns True if mark_for_demotion < 0.

        Returns:
            Whether the message should use its promotion priority
        """
        if self.mark_for_demotion is None:
            return False
        return self.mark_for_demotion >= 0

    def is_expired(self) -> bool:
        """
        Returns True if mark_for_delete < 0.

        Returns:
            Whether the message should be deleted
        """
        if self.mark_for_delete is None:
            return False
        return self.mark_for_delete < 0

    def __eq__(self, other: object) -> bool:
        """Equality based on message_id."""
        if not isinstance(other, BaseMessage):
            return False
        return self.message_id == other.message_id

    def __hash__(self) -> int:
        """Hash based on message_id."""
        return hash(self.message_id)

    def __repr__(self) -> str:
        """String representation for debugging."""
        role = self.message_dict.get("role", "unknown")
        content_preview = redact_api_keys(str(self.message_dict.get("content", "")))[:50]
        return (
            f"BaseMessage(id={self.message_id[:8]}..., "
            f"tag={self.tag}, priority={self.priority}, timestamp={self.timestamp}, "
            f"role={role}, content='{content_preview}...', )"
        )
