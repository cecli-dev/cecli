import json
import random
import weakref
from typing import Any, Dict, List
from uuid import UUID

import xxhash

from cecli.utils import is_image_file

from .service import ConversationService
from .tags import DEFAULT_TAG_PRIORITY, MessageTag


class ConversationChunks:
    _instances: Dict[UUID, "ConversationChunks"] = {}

    def __init__(self, coder):
        self.coder = weakref.ref(coder)
        self.uuid = coder.uuid

    @classmethod
    def get_instance(cls, coder) -> "ConversationChunks":
        """Get or create chunks instance for coder."""
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

    def initialize_conversation_system(self) -> None:
        """
        Initialize the conversation system with a coder instance.
        """
        coder = self.get_coder()
        if not coder:
            return

        ConversationService.get_manager(coder).initialize()
        ConversationService.get_files(coder).initialize()

    def add_system_messages(self) -> None:
        """
        Add system messages to conversation.
        """
        coder = self.get_coder()
        if not coder:
            return

        system_prompt = coder.gpt_prompts.main_system
        if system_prompt:
            # Apply system_prompt_prefix if set on the model
            if coder.main_model.system_prompt_prefix:
                system_prompt = coder.main_model.system_prompt_prefix + "\n" + system_prompt

            ConversationService.get_manager(coder).add_message(
                message_dict={"role": "system", "content": coder.fmt_system_prompt(system_prompt)},
                tag=MessageTag.SYSTEM,
                hash_key=("main", "system_prompt"),
                force=True,
            )

        # Add example messages if any
        example_messages = coder.gpt_prompts.example_messages
        if example_messages:
            for i, msg in enumerate(example_messages):
                msg_copy = msg.copy()
                msg_copy["content"] = coder.fmt_system_prompt(msg_copy["content"])
                ConversationService.get_manager(coder).add_message(
                    message_dict=msg_copy,
                    tag=MessageTag.EXAMPLES,
                    priority=75 + i,  # Slight offset for ordering within examples
                )

        # Add system reminder as a pre-prompt context block
        use_reminders = getattr(coder.args, "use_reminders", True)
        if (
            use_reminders
            and hasattr(coder.gpt_prompts, "system_reminder")
            and coder.gpt_prompts.system_reminder
        ):
            msg = dict(
                role="user",
                content=self._shuffle_reminders(
                    coder.fmt_system_prompt(coder.gpt_prompts.system_reminder)
                ),
            )
            ConversationService.get_manager(coder).add_message(
                message_dict=msg,
                tag=MessageTag.REMINDER,
                hash_key=("main", "system_reminder"),
                force=True,
                mark_for_delete=0,
            )

    def add_randomized_cta(self) -> None:
        coder = self.get_coder()
        if not coder:
            return

        message = random.choice(
            [
                "Given the above, please call any tools necessary to make progress on your task",
                (
                    "Based on the information provided, please execute the appropriate tools to"
                    " move the task forward."
                ),
                "With this context in mind, please proceed with your work.",
                (
                    "In light of the above, please utilize the required tools to continue with this"
                    " request."
                ),
                (
                    "Continue making progress. If you have reached the goal, summarize the results."
                    " Otherwise, call the next necessary tool."
                ),
                (
                    "Please use the proper tools to fulfill the next steps of this task based on"
                    " the current data."
                ),
                (
                    "You’ve got what you need, please invoke the right tools to keep making"
                    " progress towards our goal."
                ),
                (
                    "Considering what we've established, please use the available tools to complete"
                    " the current objective."
                ),
                (
                    "Given this information, please use the available tools to proceed with the"
                    " assignment."
                ),
                "Please take the next logical steps to make headway on this task.",
            ]
        )

        msg = dict(
            role="user",
            content="\n\n" + message,
        )

        ConversationService.get_manager(coder).add_message(
            message_dict=msg,
            tag=MessageTag.REMINDER,
            hash_key=("main", "randomized_cta"),
            force=True,
            mark_for_delete=0,
            promotion=2 * ConversationService.get_manager(coder).DEFAULT_TAG_PROMOTION_VALUE,
            mark_for_demotion=1,
        )

    def cleanup_files(self) -> None:
        """
        Clean up ConversationFiles and remove corresponding messages from ConversationManager
        for files that are no longer in the coder's read-only or chat file sets.
        """
        coder = self.get_coder()
        if not coder:
            return

        # Check diff message ratio and clear if too many diffs
        diff_messages = ConversationService.get_manager(coder).get_messages_dict(MessageTag.DIFFS)
        read_only_messages = ConversationService.get_manager(coder).get_messages_dict(
            MessageTag.READONLY_FILES
        )
        chat_messages = ConversationService.get_manager(coder).get_messages_dict(
            MessageTag.CHAT_FILES
        )
        edit_messages = ConversationService.get_manager(coder).get_messages_dict(
            MessageTag.EDIT_FILES
        )

        # Calculate token counts for token-based ratio check
        diff_tokens = coder.main_model.token_count(diff_messages) if diff_messages else 0

        # Calculate tokens for readonly, chat, and edit tag messages
        other_tokens = 0
        if read_only_messages:
            other_tokens += coder.main_model.token_count(read_only_messages)
        if chat_messages:
            other_tokens += coder.main_model.token_count(chat_messages)
        if edit_messages:
            other_tokens += coder.main_model.token_count(edit_messages)

        # Calculate message counts for message-based ratio check
        diff_count = len(diff_messages)
        other_count = len(read_only_messages) + len(chat_messages) + len(edit_messages)

        # Clear diff messages and file caches if EITHER:
        # 1. Diff tokens > 33% of other message tokens (token-based check)
        # 2. Diff message count ratio > 5:1 (message count-based check for periodic refresh)
        should_clear = False

        # Token-based check
        if diff_tokens > 0 and other_tokens > 0 and diff_tokens / other_tokens > 0.33:
            should_clear = True

        # Message count-based check (for periodic refresh)
        if diff_count > 0 and other_count > 0 and diff_count / other_count > 20:
            should_clear = True

        if should_clear:
            # Clear all diff messages
            ConversationService.get_manager(coder).clear_tag(MessageTag.DIFFS)
            ConversationService.get_manager(coder).clear_tag(MessageTag.FILE_CONTEXTS)
            # Clear ConversationFiles caches to force regeneration
            ConversationService.get_files(coder).clear_file_cache()

        # Get all tracked files (both regular and image files)
        tracked_files = ConversationService.get_files(coder).get_all_tracked_files()

        # Get joint set of files that should be tracked
        # Read-only files (absolute paths) - include both regular and stub files
        read_only_files = set()
        if hasattr(coder, "abs_read_only_fnames"):
            read_only_files = set(coder.abs_read_only_fnames)
        if hasattr(coder, "abs_read_only_stubs_fnames"):
            read_only_files = read_only_files.union(set(coder.abs_read_only_stubs_fnames))

        # Chat files (absolute paths)
        chat_files = set()
        if hasattr(coder, "abs_fnames"):
            chat_files = set(coder.abs_fnames)

        # Joint set of files that should be tracked
        should_be_tracked = read_only_files.union(chat_files)

        # Remove files from tracking that are not in the joint set
        for tracked_file in tracked_files:
            if tracked_file not in should_be_tracked:
                # Remove file from ConversationFiles cache
                ConversationService.get_files(coder).clear_file_cache(tracked_file)

                # Remove corresponding messages from ConversationManager
                # Try to remove regular file messages
                user_hash_key = ("file_user", tracked_file)
                assistant_hash_key = ("file_assistant", tracked_file)
                ConversationService.get_manager(coder).remove_message_by_hash_key(user_hash_key)
                ConversationService.get_manager(coder).remove_message_by_hash_key(
                    assistant_hash_key
                )

                # Try to remove image file messages
                image_user_hash_key = ("image_user", tracked_file)
                image_assistant_hash_key = ("image_assistant", tracked_file)
                ConversationService.get_manager(coder).remove_message_by_hash_key(
                    image_user_hash_key
                )
                ConversationService.get_manager(coder).remove_message_by_hash_key(
                    image_assistant_hash_key
                )

        ConversationService.get_manager(coder).clear_tag(MessageTag.RULES)

    def add_file_list_reminder(self) -> None:
        """
        Add a reminder message with list of readonly and editable files.
        The reminder lasts for exactly one turn (mark_for_delete=0).
        """
        coder = self.get_coder()
        if not coder:
            return

        # Get relative paths for display
        readonly_rel_files = []
        if hasattr(coder, "abs_read_only_fnames"):
            readonly_rel_files = sorted(
                [coder.get_rel_fname(f) for f in coder.abs_read_only_fnames]
            )

        editable_rel_files = []
        if hasattr(coder, "abs_fnames"):
            editable_rel_files = sorted([coder.get_rel_fname(f) for f in coder.abs_fnames])

        # Format reminder content
        reminder_lines = ['<context name="file_list">']
        if readonly_rel_files:
            reminder_lines.append("Read-only files:")
            for f in readonly_rel_files:
                reminder_lines.append(f"  - {f}")

        if editable_rel_files:
            if len(reminder_lines) > 1:  # Add separator if we already have readonly files
                reminder_lines.append("")
            reminder_lines.append("Editable files:")
            for f in editable_rel_files:
                reminder_lines.append(f"  - {f}")

        use_reminders = getattr(coder.args, "use_reminders", True)
        if use_reminders and len(reminder_lines) > 1:  # Only add reminder if there are files
            reminder_lines.append("</context>\n")
            reminder_content = "\n".join(reminder_lines)
            ConversationService.get_manager(coder).add_message(
                message_dict={
                    "role": "user",
                    "content": reminder_content,
                },
                tag=MessageTag.REMINDER,
                priority=275,  # Between post_message blocks and final reminders
                hash_key=("reminder", "file_list"),  # Unique hash_key to avoid conflicts
                mark_for_delete=0,  # Lasts for exactly one turn
            )

    def get_repo_map_string(self, repo_data: Dict[str, Any]) -> str:
        """
        Convert repository map data dict to formatted string representation.
        """
        # Get the combined and new dicts
        combined_dict = repo_data.get("combined_dict", {})
        new_dict = repo_data.get("new_dict", {})

        # If we don't have the new structure, fall back to old structure
        if not combined_dict and not new_dict:
            files_dict = repo_data.get("files", {})
            if files_dict:
                combined_dict = files_dict
                new_dict = files_dict

        # Use new_dict for the message (it contains only new elements)
        files_dict = new_dict

        # Format the dict into text
        formatted_lines = []
        has_content = False

        # Add prefix if present
        if repo_data.get("prefix"):
            formatted_lines.append(repo_data["prefix"])
            formatted_lines.append("")

        for rel_fname in sorted(files_dict.keys()):
            tags_info = files_dict[rel_fname]

            if not tags_info:
                # Special file without tags
                has_content = True
                formatted_lines.append(f"### {rel_fname}")
                formatted_lines.append("")
            else:
                formatted_lines.append(f"### {rel_fname}")

                # Sort tags by line
                sorted_tags = sorted(tags_info.items(), key=lambda x: x[1].get("line", 0))

                for tag_name, tag_info in sorted_tags:
                    has_content = True
                    kind = tag_info.get("kind", "")
                    start_line = tag_info.get("start_line", 0)
                    end_line = tag_info.get("end_line", 0)

                    # Convert to 1-based line numbers for display
                    display_start = start_line + 1 if start_line >= 0 else "?"
                    display_end = end_line + 1 if end_line >= 0 else "?"

                    if display_start == display_end:
                        formatted_lines.append(f"- {tag_name} ({kind}, line {display_start})")
                    else:
                        formatted_lines.append(
                            f"- {tag_name} ({kind}, lines {display_start}-{display_end})"
                        )

                formatted_lines.append("")

        # Remove trailing empty line if present
        if formatted_lines and formatted_lines[-1] == "":
            formatted_lines.pop()

        if formatted_lines and has_content:
            return "\n".join(formatted_lines)
        else:
            return ""

    def add_repo_map_messages(self) -> List[Dict[str, Any]]:
        """
        Get repository map messages using new system.
        """
        coder = self.get_coder()
        if not coder:
            return []

        # Check if we have too many REPO tagged messages (20 or more)
        repo_messages = ConversationService.get_manager(coder).get_messages_dict(MessageTag.REPO)
        if len(repo_messages) >= 20:
            # Clear all REPO tagged messages
            ConversationService.get_manager(coder).clear_tag(MessageTag.REPO)
            # Clear the combined repomap dict to force fresh regeneration
            if (
                hasattr(coder, "repo_map")
                and coder.repo_map is not None
                and hasattr(coder.repo_map, "combined_map_dict")
            ):
                coder.repo_map.combined_map_dict = {}

        # Get repository map content
        if hasattr(coder, "get_repo_map"):
            repo_data = coder.get_repo_map()
        else:
            return []

        if not repo_data:
            return []

        # Get the combined and new dicts
        combined_dict = repo_data.get("combined_dict", {})
        new_dict = repo_data.get("new_dict", {})

        # If we don't have the new structure, fall back to old structure
        if not combined_dict and not new_dict:
            files_dict = repo_data.get("files", {})
            if files_dict:
                combined_dict = files_dict
                new_dict = files_dict

        repo_messages = []

        # Determine which dict to use based on whether they're the same
        # If combined_dict and new_dict are the same (first run), use new_dict with normal priority
        # If they're different (subsequent runs), use new_dict with priority 200

        # Check if dicts are the same (deep comparison)
        combined_json = xxhash.xxh3_128_hexdigest(
            json.dumps(combined_dict, sort_keys=True).encode("utf-8")
        )
        new_json = xxhash.xxh3_128_hexdigest(json.dumps(new_dict, sort_keys=True).encode("utf-8"))
        dicts_are_same = combined_json == new_json

        # Get formatted repository content using the helper function
        repo_content = self.get_repo_map_string(repo_data)

        if repo_content:  # Only add messages if there's content
            # Create repository map messages
            dict_repo_messages = [
                dict(role="user", content=repo_content),
                dict(
                    role="assistant",
                    content="Ok, I won't try and edit those files without asking first.",
                ),
            ]

            # Add messages to conversation manager with appropriate priority
            for i, msg in enumerate(dict_repo_messages):
                priority = None if dicts_are_same else 200
                content_hash = xxhash.xxh3_128_hexdigest(repo_content.encode("utf-8"))

                ConversationService.get_manager(coder).add_message(
                    message_dict=msg,
                    tag=MessageTag.REPO,
                    priority=priority,
                    hash_key=("repo", msg["role"], content_hash),
                )

            repo_messages.extend(dict_repo_messages)

        return repo_messages

    def add_rules_messages(self) -> List[Dict[str, Any]]:
        """
        Get rules file messages for reference.
        These are always reloaded from disk and use the RULES tag.
        """
        coder = self.get_coder()
        if not coder:
            return []

        messages = []
        if not hasattr(coder, "abs_rules_fnames") or not coder.abs_rules_fnames:
            return messages

        for fname in sorted(coder.abs_rules_fnames):
            # Read file content directly from disk
            try:
                content = coder.io.read_text(fname)
                if content is None:
                    continue

            except Exception:
                continue

            rel_fname = coder.get_rel_fname(fname)

            # Create user message
            user_msg = {
                "role": "user",
                "content": f"Rules defined in {rel_fname}:\n\n{content}",
            }
            # Create assistant message
            assistant_msg = {
                "role": "assistant",
                "content": f"I understand the rules in {rel_fname} and will follow them.",
            }

            # Add to ConversationManager with RULES tag
            ConversationService.get_manager(coder).add_message(
                message_dict=user_msg,
                tag=MessageTag.RULES,
                hash_key=("rules_user", fname),
                force=True,
                update_timestamp=False,
            )

            ConversationService.get_manager(coder).add_message(
                message_dict=assistant_msg,
                tag=MessageTag.RULES,
                hash_key=("rules_assistant", fname),
                force=True,
                update_timestamp=False,
            )

            messages.extend([user_msg, assistant_msg])

        return messages

    def add_readonly_files_messages(self) -> List[Dict[str, Any]]:
        """
        Get read-only file messages using new system.
        """
        coder = self.get_coder()
        if not coder:
            return []

        messages = []
        refresh = not coder.file_diffs

        # Separate image files from regular files
        regular_files = []
        image_files = []

        # Collect all read-only files (including stubs)
        all_readonly_files = []
        if hasattr(coder, "abs_read_only_fnames"):
            all_readonly_files.extend(coder.abs_read_only_fnames)
        if hasattr(coder, "abs_read_only_stubs_fnames"):
            all_readonly_files.extend(coder.abs_read_only_stubs_fnames)

        for fname in all_readonly_files:
            if is_image_file(fname):
                image_files.append(fname)
            else:
                regular_files.append(fname)

        # Process regular files
        for fname in regular_files:
            # First, add file to cache and check for changes
            ConversationService.get_files(coder).add_file(fname, force_refresh=refresh)

            # Get file content (with proper caching and stub generation)
            content = ConversationService.get_files(coder).get_file_stub(fname)
            if content:
                # Add user message with file path as hash_key
                rel_fname = coder.get_rel_fname(fname)

                # Create user message
                file_preamble = "Original File Contents For:"
                file_postamble = "Modifications will be communicated as diff messages.\n\n"

                if refresh:
                    file_preamble = "Current File Contents For:"
                    file_postamble = ""

                user_msg = {
                    "role": "user",
                    "content": f"{file_preamble}\n{rel_fname}\n\n{content}\n\n{file_postamble}",
                }

                ConversationService.get_manager(coder).add_message(
                    message_dict=user_msg,
                    tag=MessageTag.READONLY_FILES,
                    hash_key=("file_user", fname),  # Use file path as part of hash_key
                    force=True,
                    update_timestamp=False,
                )
                messages.append(user_msg)

                # Add assistant message with file path as hash_key
                assistant_msg = {
                    "role": "assistant",
                    "content": "I understand, thank you for sharing the file contents.",
                }
                ConversationService.get_manager(coder).add_message(
                    message_dict=assistant_msg,
                    tag=MessageTag.READONLY_FILES,
                    hash_key=("file_assistant", fname),  # Use file path as part of hash_key
                    force=True,
                    update_timestamp=False,
                )
                messages.append(assistant_msg)

            # Check if file has changed and add diff message if needed
            if ConversationService.get_files(coder).has_file_changed(fname):
                ConversationService.get_files(coder).update_file_diff(fname)

        # Handle image files using coder.get_images_message()
        if image_files:
            image_messages = coder.get_images_message(image_files)
            for img_msg in image_messages:
                # Add individual image message to result
                messages.append(img_msg)

                # Add individual assistant acknowledgment for each image
                assistant_msg = {
                    "role": "assistant",
                    "content": "Ok, I will use this image as a reference.",
                }
                messages.append(assistant_msg)

                # Get the file name from the message (stored in image_file key)
                fname = img_msg.get("image_file")
                if fname:
                    # Add to ConversationManager with individual file hash key
                    ConversationService.get_manager(coder).add_message(
                        message_dict=img_msg,
                        tag=MessageTag.READONLY_FILES,
                        hash_key=("image_user", fname),
                    )
                    ConversationService.get_manager(coder).add_message(
                        message_dict=assistant_msg,
                        tag=MessageTag.READONLY_FILES,
                        hash_key=("image_assistant", fname),
                    )

        return messages

    def add_chat_files_messages(self) -> Dict[str, Any]:
        """
        Get chat file messages using new system.
        """
        coder = self.get_coder()
        if not coder:
            return {"chat_files": [], "edit_files": []}

        result = {"chat_files": [], "edit_files": []}
        refresh = not coder.file_diffs

        if not hasattr(coder, "abs_fnames"):
            return result

        # First, handle regular (non-image) files
        regular_files = []
        image_files = []

        # Separate image files from regular files
        for fname in coder.abs_fnames:
            if is_image_file(fname):
                image_files.append(fname)
            else:
                regular_files.append(fname)

        # Process regular files
        for fname in regular_files:
            # First, add file to cache and check for changes
            ConversationService.get_files(coder).add_file(fname, force_refresh=refresh)

            # Get file content (with proper caching and stub generation)
            content = ConversationService.get_files(coder).get_file_stub(fname)
            if not content:
                ConversationService.get_files(coder).clear_file_cache(fname)
                continue

            rel_fname = coder.get_rel_fname(fname)

            # Create user message
            file_preamble = "Original File Contents For:"
            file_postamble = "Modifications will be communicated as diff messages.\n\n"

            if refresh:
                file_preamble = "Current File Contents For:"
                file_postamble = ""

            user_msg = {
                "role": "user",
                "content": f"{file_preamble}\n{rel_fname}\n\n{content}\n\n{file_postamble}",
            }

            # Create assistant message
            assistant_msg = {
                "role": "assistant",
                "content": "I understand, thank you for sharing the file contents.",
            }

            # Determine tag based on editability
            tag = MessageTag.CHAT_FILES
            result["chat_files"].extend([user_msg, assistant_msg])

            # Add user message to ConversationManager with file path as hash_key
            ConversationService.get_manager(coder).add_message(
                message_dict=user_msg,
                tag=tag,
                hash_key=("file_user", fname),  # Use file path as part of hash_key
                force=True,
                update_timestamp=False,
            )

            # Add assistant message to ConversationManager with file path as hash_key
            ConversationService.get_manager(coder).add_message(
                message_dict=assistant_msg,
                tag=tag,
                hash_key=("file_assistant", fname),  # Use file path as part of hash_key
                force=True,
                update_timestamp=False,
            )

            # Check if file has changed and add diff message if needed
            if ConversationService.get_files(coder).has_file_changed(fname):
                ConversationService.get_files(coder).update_file_diff(fname)

        # Handle image files using coder.get_images_message()
        if image_files:
            image_messages = coder.get_images_message(image_files)
            for img_msg in image_messages:
                # Add individual image message to result
                result["chat_files"].append(img_msg)

                # Add individual assistant acknowledgment for each image
                assistant_msg = {
                    "role": "assistant",
                    "content": "Ok, I will use this image as a reference.",
                }
                result["chat_files"].append(assistant_msg)

                # Get the file name from the message (stored in image_file key)
                fname = img_msg.get("image_file")
                if fname:
                    # Add to ConversationManager with individual file hash key
                    ConversationService.get_manager(coder).add_message(
                        message_dict=img_msg,
                        tag=MessageTag.CHAT_FILES,
                        hash_key=("image_user", fname),
                    )
                    ConversationService.get_manager(coder).add_message(
                        message_dict=assistant_msg,
                        tag=MessageTag.CHAT_FILES,
                        hash_key=("image_assistant", fname),
                    )

        return result

    def add_file_context_messages(self, promote_messages=True) -> None:
        """
        Create and insert FILE_CONTEXTS messages based on cached contexts.
        """
        coder = self.get_coder()
        if not coder:
            return

        # Get numbered contexts
        numbered_contexts = ConversationService.get_files(coder)._get_numbered_contexts()

        for file_path, ranges in numbered_contexts.items():
            if not ranges:
                continue

            # Generate context content
            context_content = ConversationService.get_files(coder).get_file_context(file_path)
            if not context_content:
                continue

            # Get relative file name
            rel_fname = coder.get_rel_fname(file_path)

            user_msg = {
                "role": "user",
                "content": f"Hashline-Prefixed Context For:\n{rel_fname}\n\n{context_content}",
            }

            assistant_msg = {
                "role": "assistant",
                "content": "I understand, thank you for sharing the prefixed file contents.",
            }

            # Add to conversation manager
            ConversationService.get_manager(coder).add_message(
                message_dict=user_msg,
                tag=MessageTag.FILE_CONTEXTS,
                hash_key=("file_context_user", file_path),
                force=True,
            )

            ConversationService.get_manager(coder).add_message(
                message_dict=assistant_msg,
                tag=MessageTag.FILE_CONTEXTS,
                hash_key=("file_context_assistant", file_path),
                force=True,
            )

    def reset(self) -> None:
        """
        Reset the entire conversation system to initial state.
        """
        coder = self.get_coder()
        ConversationService.get_manager(coder).reset()
        if coder:
            ConversationService.get_files(coder).reset()

    def add_static_context_blocks(self) -> None:
        """
        Add static context blocks to conversation (priority 50).

        Static blocks include: environment_info, directory_structure, skills
        """
        coder = self.get_coder()
        if not coder:
            return

        if not hasattr(coder, "use_enhanced_context") or not coder.use_enhanced_context:
            return

        # Ensure tokens are calculated
        if hasattr(coder, "_calculate_context_block_tokens"):
            coder._calculate_context_block_tokens()

        # Add static blocks as dict with block type as key
        message_blocks = {}
        if hasattr(coder, "allowed_context_blocks"):
            if "environment_info" in coder.allowed_context_blocks:
                block = coder.get_cached_context_block("environment_info")
                if block:
                    message_blocks["environment_info"] = block
            if "directory_structure" in coder.allowed_context_blocks:
                block = coder.get_cached_context_block("directory_structure")
                if block:
                    message_blocks["directory_structure"] = block
            if "skills" in coder.allowed_context_blocks:
                block = coder._generate_context_block("skills")
                if block:
                    message_blocks["skills"] = block

        # Add static blocks to conversation manager with stable hash keys
        for block_type, block_content in message_blocks.items():
            ConversationService.get_manager(coder).add_message(
                message_dict={"role": "user", "content": block_content},
                tag=MessageTag.STATIC,
                hash_key=("static", block_type),
                force=True,
            )

    def add_pre_message_context_blocks(self) -> None:
        """
        Add pre-message context blocks to conversation (priority 125).

        Pre-message blocks include: symbol_outline, git_status, todo_list,
        loaded_skills, context_summary
        """
        coder = self.get_coder()
        if not coder:
            return

        if not hasattr(coder, "use_enhanced_context") or not coder.use_enhanced_context:
            return

        # Ensure tokens are calculated
        if hasattr(coder, "_calculate_context_block_tokens"):
            coder._calculate_context_block_tokens()

        # Add pre-message blocks as dict with block type as key
        message_blocks = {}
        if hasattr(coder, "allowed_context_blocks"):
            if "symbol_outline" in coder.allowed_context_blocks:
                block = coder.get_cached_context_block("symbol_outline")
                if block:
                    message_blocks["symbol_outline"] = block
            if "git_status" in coder.allowed_context_blocks:
                block = coder.get_cached_context_block("git_status")
                if block:
                    message_blocks["git_status"] = block
            if "skills" in coder.allowed_context_blocks:
                block = coder._generate_context_block("loaded_skills")
                if block:
                    message_blocks["loaded_skills"] = block

        # Process other blocks
        for block_type, block_content in message_blocks.items():
            ConversationService.get_manager(coder).add_message(
                message_dict={"role": "user", "content": block_content},
                tag=MessageTag.STATIC,  # Use STATIC tag but with different priority
                priority=125,  # Between REPO (100) and READONLY_FILES (200)
                hash_key=("pre_message", block_type),
                force=True,
            )

    def add_post_message_context_blocks(self) -> None:
        """
        Add post-message context blocks to conversation (priority 250).

        Post-message blocks include: tool_context/write_context, background_command_output
        """
        coder = self.get_coder()
        if not coder:
            return

        if not hasattr(coder, "use_enhanced_context") or not coder.use_enhanced_context:
            return

        # Add post-message blocks as dict with block type as key
        message_blocks = {}

        if hasattr(coder, "allowed_context_blocks"):
            if "todo_list" in coder.allowed_context_blocks:
                block = coder.get_todo_list()
                if block:
                    message_blocks["todo_list"] = block

            if "context_summary" in coder.allowed_context_blocks:
                block = coder.get_context_summary()
                if block:
                    # Store context_summary separately since it goes first
                    message_blocks["context_summary"] = block

        # Add tool context or write context
        if hasattr(coder, "tool_usage_history") and coder.tool_usage_history:
            if hasattr(coder, "_get_repetitive_tools"):
                repetitive_tools = coder._get_repetitive_tools()
                if repetitive_tools:
                    if hasattr(coder, "_generate_tool_context"):
                        tool_context = coder._generate_tool_context(repetitive_tools)
                        if tool_context:
                            message_blocks["tool_context"] = tool_context
                else:
                    if hasattr(coder, "_generate_write_context"):
                        write_context = coder._generate_write_context()
                        if write_context:
                            message_blocks["write_context"] = write_context

        # Add background command output if any
        if hasattr(coder, "get_background_command_output"):
            bg_output = coder.get_background_command_output()
            if bg_output:
                message_blocks["background_command_output"] = bg_output

        # Add post-message blocks to conversation manager with stable hash keys
        for block_type, block_content in message_blocks.items():
            ConversationService.get_manager(coder).add_message(
                message_dict={"role": "user", "content": block_content},
                tag=MessageTag.STATIC,  # Use STATIC tag but with different priority
                priority=DEFAULT_TAG_PRIORITY[MessageTag.REMINDER] + 25,  # After REMINDER (300)
                mark_for_delete=0,
                hash_key=("post_message", block_type),
                force=True,
            )

    def _shuffle_reminders(self, content: str) -> str:
        """
        If the string is a critical_reminders block, shuffle all bulleted points
        to prevent the model from developing 'boilerplate blindness.'
        """
        if not content.strip().startswith('<context name="critical_reminders">'):
            return content

        lines = content.splitlines()

        # 1. Identify indices of lines starting with a hyphen (and the content itself)
        # We use strip() to handle indentation within the XML block
        list_info = [(i, line) for i, line in enumerate(lines) if line.strip().startswith("-")]

        if not list_info:
            return content

        # 2. Extract and shuffle the list items
        indices = [item[0] for item in list_info]
        bullet_contents = [item[1] for item in list_info]
        random.shuffle(bullet_contents)

        # 3. Reconstruct the block by placing shuffled items back into the original indices
        new_lines = list(lines)
        for index, shuffled_text in zip(indices, bullet_contents):
            new_lines[index] = shuffled_text

        return "\n".join(new_lines)

    def debug_print_conversation_state(self) -> None:
        """
        Print debug information about conversation state.
        """
        coder = self.get_coder()
        print("=== Conversation Manager State ===")
        ConversationService.get_manager(coder).debug_print_stream()
        if coder:
            print("\n=== Conversation Files State ===")
            ConversationService.get_files(coder).debug_print_cache()
