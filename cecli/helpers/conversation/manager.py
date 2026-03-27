import copy
import json
import time
import weakref
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

from cecli.helpers import nested

from .base_message import BaseMessage
from .tags import MessageTag, get_default_priority, get_default_timestamp_offset


class ConversationManager:
    _instances: Dict[UUID, "ConversationManager"] = {}

    def __init__(self, coder):
        self.coder = weakref.ref(coder)
        self.uuid = coder.uuid
        self._messages: List[BaseMessage] = []
        self._message_index: Dict[str, BaseMessage] = {}
        self._initialized = False
        self._debug_enabled = False
        self._previous_messages_dict: List[Dict[str, Any]] = []
        self._tag_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._ALL_MESSAGES_CACHE_KEY = "__all__"
        self.DEFAULT_TAG_PROMOTION_VALUE: int = 999

    @classmethod
    def get_instance(cls, coder) -> "ConversationManager":
        """Get or create manager for coder."""
        if coder.uuid not in cls._instances:
            cls._instances[coder.uuid] = cls(coder)

        # Update weakref for SwitchCoderSignal
        if coder is not cls._instances[coder.uuid].get_coder():
            cls._instances[coder.uuid].coder = weakref.ref(coder)

        return cls._instances[coder.uuid]

    @classmethod
    def destroy_instance(cls, coder_uuid: UUID):
        """Explicit cleanup for sub-agents."""
        if coder_uuid in cls._instances:
            del cls._instances[coder_uuid]

    def get_coder(self):
        """Get strong reference to coder (or None if destroyed)."""
        return self.coder()

    def initialize(
        self,
        reset: bool = False,
        reformat: bool = False,
        preserve_tags: Optional[Union[List[str], bool]] = None,
    ) -> None:
        """Set up manager with weak reference to coder."""
        coder = self.get_coder()
        if not coder:
            return

        self._initialized = True

        preserved_messages = []
        if preserve_tags is True:
            preserve_tags = [
                MessageTag.DONE,
                MessageTag.CUR,
                MessageTag.DIFFS,
                MessageTag.FILE_CONTEXTS,
            ]

        if reset and preserve_tags:
            all_tag_types = list(MessageTag)
            for tag_type in all_tag_types:
                if tag_type.value not in preserve_tags:
                    self.clear_tag(tag_type)
            preserved_messages = self.get_messages()
        elif reset:
            self.reset()

        if reformat:
            if hasattr(coder, "format_chat_chunks"):
                coder.format_chat_chunks()

        if preserve_tags and preserved_messages:
            offset = 0
            for msg in preserved_messages:
                offset += 1
                msg.timestamp = time.monotonic_ns() + offset

        if hasattr(coder, "verbose") and coder.verbose:
            self._debug_enabled = True

    def set_debug_enabled(self, enabled: bool) -> None:
        """
        Enable or disable debug mode.

        Args:
            enabled: True to enable debug mode, False to disable
        """
        self._debug_enabled = enabled
        if enabled:
            print(f"[DEBUG] ConversationManager debug mode enabled for coder {self.uuid}")
        else:
            print(f"[DEBUG] ConversationManager debug mode disabled for coder {self.uuid}")

    def add_message(
        self,
        message_dict: Dict[str, Any],
        tag: str,
        priority: Optional[int] = None,
        timestamp: Optional[int] = None,
        mark_for_delete: Optional[int] = None,
        mark_for_demotion: Optional[int] = None,
        promotion: Optional[int] = None,
        hash_key: Optional[Tuple[str, ...]] = None,
        force: bool = False,
        update_timestamp: bool = True,
        update_promotion: bool = False,
        message_id: Optional[str] = None,
    ) -> BaseMessage:
        """
        Idempotently add message if hash not already present.
        Update if force=True and hash exists.

        Args:
            message_dict: Message content dictionary
            tag: Message tag (must be valid MessageTag)
            priority: Priority value (lower = earlier)
            timestamp: Creation timestamp in nanoseconds
            mark_for_delete: Countdown for deletion (None = permanent)
            mark_for_demotion: Countdown for demotion (None = permanent)
            promotion: Promotion priority value
            hash_key: Optional tuple for pattern-based removal
            force: Whether to update existing message
            update_timestamp: Whether to update timestamp on force update
            update_promotion: Whether to update promotion on force update
            message_id: Optional explicit message ID
        """
        if not isinstance(tag, MessageTag):
            try:
                tag = MessageTag(tag)
            except ValueError:
                raise ValueError(f"Invalid tag: {tag}")

        if priority is None:
            priority = get_default_priority(tag)

        if timestamp is None:
            timestamp = time.monotonic_ns() + get_default_timestamp_offset(tag)

        message = BaseMessage(
            message_dict=message_dict,
            tag=tag.value,
            priority=priority,
            timestamp=timestamp,
            mark_for_delete=mark_for_delete,
            mark_for_demotion=mark_for_demotion,
            promotion=promotion,
            hash_key=hash_key,
            message_id=message_id,
        )

        # Check if message already exists
        existing_message = self._message_index.get(message.message_id)

        if existing_message:
            if force:
                # Update existing message
                existing_message.message_dict = message_dict
                existing_message.tag = tag.value
                existing_message.priority = priority
                if update_timestamp:
                    existing_message.timestamp = timestamp
                if update_promotion:
                    existing_message.mark_for_demotion = mark_for_demotion
                    existing_message.promotion = promotion
                existing_message.mark_for_delete = mark_for_delete
                # Clear cache for this tag and all messages cache since message was updated
                self._tag_cache.pop(tag.value, None)
                self._tag_cache.pop(self._ALL_MESSAGES_CACHE_KEY, None)
                return existing_message
            else:
                # Return existing message without updating
                return existing_message
        else:
            # Add new message
            self._messages.append(message)
            self._message_index[message.message_id] = message
            # Clear cache for this tag and all messages cache since new message was added
            self._tag_cache.pop(tag.value, None)
            self._tag_cache.pop(self._ALL_MESSAGES_CACHE_KEY, None)
            return message

    def base_sort(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Sorts messages by effective priority (promotion if mark_for_demotion has not elapsed yet), then timestamp.

        Args:
            messages: List of BaseMessage instances to sort

        Returns:
            Sorted list of messages
        """
        return [
            msg
            for _, msg in sorted(
                enumerate(messages),
                key=lambda pair: (
                    (
                        pair[1].promotion
                        if pair[1].is_promoted() and pair[1].promotion is not None
                        else pair[1].priority
                    ),
                    pair[1].timestamp,
                    pair[0],
                ),
            )
        ]

    def get_messages(self) -> List[BaseMessage]:
        """
        Returns messages sorted by priority (lowest first), then raw order in list.

        Returns:
            List of BaseMessage instances in sorted order
        """
        # Filter out expired messages first
        self._remove_expired_messages()

        return self.base_sort(self._messages)

    def get_messages_dict(
        self, tag: Optional[str] = None, reload: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Returns sorted list of message_dict for LLM consumption.

        Args:
            tag: Optional tag to filter messages by. If None, returns all messages.
            reload: If True, bypass cache and recompute the result

        Returns:
            List of message dictionaries in sorted order
        """
        coder = self.get_coder()

        # Check cache for all queries (including tag=None)
        if not reload:
            if tag is not None:
                if not isinstance(tag, MessageTag):
                    try:
                        tag = MessageTag(tag)
                    except ValueError:
                        raise ValueError(f"Invalid tag: {tag}")
                cache_key = tag.value
            else:
                cache_key = self._ALL_MESSAGES_CACHE_KEY

            # Return cached result if available
            if cache_key in self._tag_cache:
                return self._tag_cache[cache_key]

        messages = self.get_messages()

        # Filter by tag if specified
        if tag is not None:
            if not isinstance(tag, MessageTag):
                try:
                    tag = MessageTag(tag)
                except ValueError:
                    raise ValueError(f"Invalid tag: {tag}")
            tag_str = tag.value
            messages = [msg for msg in messages if msg.tag == tag_str]

        messages_dict = [msg.to_dict() for msg in messages]

        # Cache the result for all queries (including tag=None)
        if tag is not None:
            if not isinstance(tag, MessageTag):
                try:
                    tag = MessageTag(tag)
                except ValueError:
                    raise ValueError(f"Invalid tag: {tag}")
            cache_key = tag.value
        else:
            cache_key = self._ALL_MESSAGES_CACHE_KEY

        self._tag_cache[cache_key] = messages_dict

        # Debug: Compare with previous messages if debug is enabled
        # We need to compare the full unfiltered message stream, not just filtered views
        if self._debug_enabled and tag is None:
            # Get the full unfiltered messages for comparison
            all_messages = self.get_messages()
            all_messages_dict = [msg.to_dict() for msg in all_messages]

            # Compare with previous full message dict
            self._debug_compare_messages(self._previous_messages_dict, all_messages_dict)

            # Store current full message dict for next comparison
            self._previous_messages_dict = all_messages_dict

        if (self._debug_enabled and tag is None) or (
            nested.getter(coder, "args.debug") and tag is None
        ):
            import os

            os.makedirs(".cecli/logs", exist_ok=True)
            with open(".cecli/logs/conversation.log", "w") as f:
                json.dump(messages_dict, f, indent=4, default=lambda o: "<not serializable>")

        # Add cache control headers when getting all messages (for LLM consumption)
        # Only add cache control if the coder has add_cache_headers = True
        if tag is None:
            if (
                coder
                and hasattr(coder, "add_cache_headers")
                and coder.add_cache_headers
                and hasattr(coder, "main_model")
                and not coder.main_model.caches_by_default
            ):
                messages_dict = self._add_cache_control(messages_dict)
        return messages_dict

    def clear_tag(self, tag: str) -> None:
        """Remove all messages with given tag."""
        if not isinstance(tag, MessageTag):
            try:
                tag = MessageTag(tag)
            except ValueError:
                raise ValueError(f"Invalid tag: {tag}")

        tag_str = tag.value
        messages_to_remove = []

        for message in self._messages:
            if message.tag == tag_str:
                messages_to_remove.append(message)

        for message in messages_to_remove:
            self._messages.remove(message)
            del self._message_index[message.message_id]

        # Clear cache for this tag and all messages cache since messages were removed
        if messages_to_remove:
            self._tag_cache.pop(tag_str, None)
            self._tag_cache.pop(self._ALL_MESSAGES_CACHE_KEY, None)

    def remove_messages_by_hash_key_pattern(self, pattern_checker) -> None:
        """
        Remove messages whose hash_key matches a pattern.

        Args:
            pattern_checker: A function that takes a hash_key (tuple) and returns True
                            if the message should be removed
        """
        messages_to_remove = []

        for message in self._messages:
            if message.hash_key and pattern_checker(message.hash_key):
                messages_to_remove.append(message)

        # Remove messages and track affected tags
        tags_to_clear = set()
        for message in messages_to_remove:
            self._messages.remove(message)
            del self._message_index[message.message_id]
            tags_to_clear.add(message.tag)

        # Clear cache for affected tags and all messages cache if any messages were removed
        if messages_to_remove:
            for tag in tags_to_clear:
                self._tag_cache.pop(tag, None)
            self._tag_cache.pop(self._ALL_MESSAGES_CACHE_KEY, None)

    def remove_message_by_hash_key(self, hash_key: Tuple[str, ...]) -> bool:
        """
        Remove a message by its exact hash key.

        Args:
            hash_key: The exact hash key to match

        Returns:
            True if a message was removed, False otherwise
        """
        messages_to_remove = [m for m in self._messages if m.hash_key == hash_key]
        if not messages_to_remove:
            return False

        tags_to_clear = set()
        for message in messages_to_remove:
            self._messages.remove(message)
            if message.message_id in self._message_index:
                del self._message_index[message.message_id]
            tags_to_clear.add(message.tag)

        for tag in tags_to_clear:
            self._tag_cache.pop(tag, None)
        self._tag_cache.pop(self._ALL_MESSAGES_CACHE_KEY, None)

        return True

    def get_tag_messages(self, tag: str) -> List[BaseMessage]:
        """Get all messages of given tag in sorted order."""
        if not isinstance(tag, MessageTag):
            try:
                tag = MessageTag(tag)
            except ValueError:
                raise ValueError(f"Invalid tag: {tag}")

        tag_str = tag.value
        messages = [msg for msg in self._messages if msg.tag == tag_str]
        return self.base_sort(messages)

    def decrement_message_markers(self) -> None:
        """Decrement all mark_for_delete values, remove expired messages."""
        messages_to_remove = []

        for message in self._messages:
            if message.mark_for_delete is not None:
                message.mark_for_delete -= 1
                if message.is_expired():
                    messages_to_remove.append(message)

            if message.mark_for_demotion is not None:
                message.mark_for_demotion -= 1

        # Remove expired messages and clear cache for each tag
        tags_to_clear = set()
        for message in messages_to_remove:
            self._messages.remove(message)
            del self._message_index[message.message_id]
            tags_to_clear.add(message.tag)

        # Clear cache for affected tags and all messages cache if any messages were removed
        if messages_to_remove:
            for tag in tags_to_clear:
                self._tag_cache.pop(tag, None)
            self._tag_cache.pop(self._ALL_MESSAGES_CACHE_KEY, None)

    def reset(self) -> None:
        """Clear all messages and reset to initial state."""
        self._messages.clear()
        self._message_index.clear()
        self._initialized = False
        self._tag_cache.clear()
        self._previous_messages_dict.clear()

    def clear_cache(self) -> None:
        """Clear the tag cache."""
        self._tag_cache.clear()

    def _remove_expired_messages(self) -> None:
        """Internal method to remove expired messages."""
        messages_to_remove = []

        for message in self._messages:
            if message.is_expired():
                messages_to_remove.append(message)

        for message in messages_to_remove:
            self._messages.remove(message)
            del self._message_index[message.message_id]

    # Debug methods
    def debug_print_stream(self) -> None:
        """Print the conversation stream with hashes, priorities, timestamps, and tags."""
        messages = self.get_messages()
        print(f"Conversation Stream ({len(messages)} messages):")
        for i, msg in enumerate(messages):
            role = msg.message_dict.get("role", "unknown")
            content_preview = str(msg.message_dict.get("content", ""))[:50]
            print(
                f"  {i:3d}. [{msg.priority:3d}] {msg.timestamp:15d} "
                f"{msg.tag:15s} {role:7s} {msg.message_id[:8]}... "
                f"'{content_preview}...'"
            )

    def debug_get_stream_info(self) -> Dict[str, Any]:
        """Return dict with stream length, hash list, and modification count."""
        messages = self.get_messages()
        return {
            "stream_length": len(messages),
            "message_count": len(self._messages),
            "hashes": [msg.message_id[:8] for msg in messages],
            "tags": [msg.tag for msg in messages],
            "priorities": [msg.priority for msg in messages],
            "debug_enabled": self._debug_enabled,
        }

    def debug_validate_state(self) -> bool:
        """Validate internal consistency of message list and index."""
        # Check that all messages in list are in index
        for msg in self._messages:
            if msg.message_id not in self._message_index:
                return False
            if self._message_index[msg.message_id] is not msg:
                return False

        # Check that all messages in index are in list
        for msg_id, msg in self._message_index.items():
            if msg not in self._messages:
                return False
            if msg.message_id != msg_id:
                return False

        # Check for duplicate message IDs
        message_ids = [msg.message_id for msg in self._messages]
        if len(message_ids) != len(set(message_ids)):
            return False

        return True

    def _debug_compare_messages(
        self, messages_before: List[Dict[str, Any]], messages_after: List[Dict[str, Any]]
    ) -> None:
        """
        Debug helper to compare messages before and after adding new chunk ones calculation.

        Args:
            messages_before: List of messages before adding new ones
            messages_after: List of messages after adding new ones
        """
        # Log total counts
        print(f"[DEBUG] Messages before: {len(messages_before)} entries")
        print(f"[DEBUG] Messages after: {len(messages_after)} entries")

        # Find indices that are different (excluding messages contiguously at the end)
        different_indices = []
        changed_content_size = 0

        # Compare up to the length of the shorter list
        min_len = min(len(messages_before), len(messages_after))
        first_different_index = 0
        for i in range(min_len):
            before_content = messages_before[i].get("content", "")
            after_content = messages_after[i].get("content", "")
            if before_content != after_content:
                if first_different_index == 0:
                    first_different_index = i
                different_indices.append(i)
                changed_content_size += len(str(after_content)) - len(str(before_content))

                # Log details about the difference
                before_msg = messages_before[i]
                after_msg = messages_after[i]
                print(f"[DEBUG] Changed at index {i}:")
                before_first_line = str(before_msg.get("content", "")).split("\n", 1)[0]
                after_first_line = str(after_msg.get("content", "")).split("\n", 1)[0]
                print(f"  Before: {before_first_line}...")
                print(f"  After:  {after_first_line}...")

        # Note messages added/removed at end without verbose details
        if len(messages_before) > len(messages_after):
            removed_count = len(messages_before) - len(messages_after)
            print(f"[DEBUG] {removed_count} message(s) removed contiguously from end")
        elif len(messages_after) > len(messages_before):
            added_count = len(messages_after) - len(messages_before)
            print(f"[DEBUG] {added_count} message(s) added contiguously to end")

        # Log summary of changed indices
        if different_indices:
            print(f"[DEBUG] Changed indices: {different_indices}")
        else:
            print("[DEBUG] No content changes in existing messages")

        # Calculate content sizes
        before_content_size = sum(len(str(msg.get("content", ""))) for msg in messages_before)
        after_content_size = sum(len(str(msg.get("content", ""))) for msg in messages_after)

        before_unsuffixed = messages_before[: first_different_index - 1]
        before_unsuffixed_content_size = sum(
            len(str(msg.get("content", "") or "")) for msg in before_unsuffixed
        )

        before_unsuffixed_joined = "\n".join(
            map(lambda x: x.get("content", "") or "", before_unsuffixed)
        )
        after_joined = "\n".join(map(lambda x: x.get("content", "") or "", messages_after))
        print(f"[DEBUG] Total content size before: {before_content_size} characters")
        print(f"[DEBUG] Total cacheable size before: {before_unsuffixed_content_size} characters")
        print(f"[DEBUG] Total content size after: {after_content_size} characters")
        print(
            "[DEBUG] Content size delta:"
            f" {after_content_size - before_unsuffixed_content_size} characters"
        )
        print(f"[DEBUG] Is Proper Superset: {after_joined.startswith(before_unsuffixed_joined)}")

    def _add_cache_control(self, messages_dict: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Add cache control headers to messages dict for LLM consumption.
        Uses 3 cache blocks based on message roles:
        1. Last system message at the very beginning
        2. Last user/assistant message (skips tool messages)
        3. Second-to-last user/assistant message (skips tool messages)

        Args:
            messages_dict: List of message dictionaries

        Returns:
            List of message dictionaries with cache control headers added
        """
        if not messages_dict:
            return messages_dict

        # Find indices for cache control
        system_message_idx = -1

        # First, find the real last and second-to-last messages, skipping any "<context" messages at the end
        # Only consider messages with role "user" or "assistant" (not "tool")
        last_message_idx = -1
        second_last_message_idx = -1
        seen_context = False

        # Find the last non-"<context" message with valid role
        for i in range(len(messages_dict) - 1, -1, -1):
            msg = messages_dict[i]
            content = msg.get("content", "")
            role = msg.get("role", "")
            tool_calls = msg.get("tool_calls", [])

            if tool_calls is not None and len(tool_calls) and not seen_context:
                continue

            if isinstance(content, str) and content.strip().startswith("<context"):
                seen_context = True
                if not content.strip().startswith('<context name="user_input" from="agent">'):
                    continue
                else:
                    last_message_idx = i
                    break

            if role not in ["system", "user", "assistant"]:
                continue

            if seen_context:
                last_message_idx = i
                break
            else:
                continue

        # Find the second-to-last message with valid role
        if last_message_idx >= 0:
            for i in range(last_message_idx - 1, -1, -1):
                msg = messages_dict[i]
                content = msg.get("content", "")
                role = msg.get("role", "")
                tool_calls = msg.get("tool_calls", [])

                if role not in ["system", "user", "assistant"]:
                    continue

                second_last_message_idx = i
                break

        # Find the last system message in a contiguous set at the beginning of the message list
        # Look for consecutive system messages starting from index 0
        for i in range(len(messages_dict)):
            msg = messages_dict[i]
            role = msg.get("role", "")
            if role == "system":
                # Keep track of the last system message in this contiguous block
                system_message_idx = i
            else:
                # Once we hit a non-system message, stop searching
                break

        # Add cache control to system message if found
        if system_message_idx >= 0:
            messages_dict = self._add_cache_control_to_message(messages_dict, system_message_idx)

        # Add cache control to last message
        if last_message_idx >= 0:
            messages_dict = self._add_cache_control_to_message(messages_dict, last_message_idx)

        # Add cache control to second-to-last message if it exists
        if second_last_message_idx >= 0:
            messages_dict = self._add_cache_control_to_message(
                messages_dict, second_last_message_idx, penultimate=True
            )

        return messages_dict

    def _strip_cache_control(self, messages_dict: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Strip cache control entries from messages dict.

        Args:
            messages_dict: List of message dictionaries

        Returns:
            List of message dictionaries with cache control removed
        """
        result = []
        for msg in messages_dict:
            msg_copy = dict(msg)
            content = msg_copy.get("content")

            if isinstance(content, list) and len(content) > 0:
                # Check if first element has cache_control
                first_element = content[0]
                if isinstance(first_element, dict) and "cache_control" in first_element:
                    # Remove cache_control
                    first_element.pop("cache_control", None)
                    # If content is now just a dict with text, convert back to string
                    if len(first_element) == 1 and "text" in first_element:
                        msg_copy["content"] = first_element["text"]
                    elif (
                        len(first_element) == 2
                        and "text" in first_element
                        and "type" in first_element
                    ):
                        # Keep as dict but without cache_control
                        msg_copy["content"] = [first_element]

            result.append(msg_copy)

        return result

    def _add_cache_control_to_message(
        self, messages_dict: List[Dict[str, Any]], idx: int, penultimate: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Add cache control to a specific message in the messages dict.

        Args:
            messages_dict: List of message dictionaries
            idx: Index of message to add cache control to
            penultimate: If True, marks as penultimate cache block

        Returns:
            Updated messages dict
        """
        if idx < 0 or idx >= len(messages_dict):
            return messages_dict

        msg = messages_dict[idx]
        content = msg.get("content")

        # Convert string content to dict format if needed
        if isinstance(content, str):
            content = {
                "type": "text",
                "text": content,
            }
        elif isinstance(content, list) and len(content) > 0:
            # If already a list, get the first element
            first_element = content[0]
            if isinstance(first_element, dict):
                content = first_element
            else:
                # If first element is not a dict, wrap it
                content = {
                    "type": "text",
                    "text": str(first_element),
                }
        elif content is None:
            # Handle None content (e.g., tool calls)
            content = {
                "type": "text",
                "text": "",
            }

        # Add cache control
        content["cache_control"] = {"type": "ephemeral"}

        # Wrap in list
        msg_copy = copy.deepcopy(msg)
        msg_copy["content"] = [content]

        # Create new list with updated message
        result = list(messages_dict)
        result[idx] = msg_copy

        return result
