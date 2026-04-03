import os
import weakref
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from cecli.helpers.hashline import get_hashline_content_diff, hashline
from cecli.repomap import RepoMap

from .service import ConversationService
from .tags import MessageTag


class ConversationFiles:
    """
    Handles file content caching, change detection,
    and diff generation for file-based messages.
    """

    _instances: Dict[UUID, "ConversationFiles"] = {}

    def __init__(self, coder):
        self.coder = weakref.ref(coder)
        self.uuid = coder.uuid
        self._file_contents_original: Dict[str, str] = {}
        self._file_contents_snapshot: Dict[str, str] = {}
        self._file_timestamps: Dict[str, float] = {}
        self._file_diffs: Dict[str, str] = {}
        self._file_to_message_id: Dict[str, str] = {}
        self._image_files: Dict[str, bool] = {}
        self._numbered_contexts: Dict[str, List[Tuple[int, int]]] = {}
        self._initialized = True

    @classmethod
    def get_instance(cls, coder) -> "ConversationFiles":
        """Get or create files instance for coder."""
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

    def initialize(self) -> None:
        """Initialize (already handled in __init__)."""
        self._initialized = True

    def add_file(
        self,
        fname: str,
        content: Optional[str] = None,
        force_refresh: bool = False,
    ) -> str:
        """
        Add file to cache, reading from disk if content not provided.

        Args:
            fname: Absolute file path
            content: File content (if None, read from disk)
            force_refresh: If True, force re-reading from disk

        Returns:
            The file content (cached or newly read)
        """
        # Get absolute path
        abs_fname = os.path.abspath(fname)

        # Check if we need to refresh
        current_mtime = os.path.getmtime(abs_fname) if os.path.exists(abs_fname) else 0

        if force_refresh or abs_fname not in self._file_contents_original:
            # Read content from disk if not provided
            if content is None:
                # Use coder.io.read_text() - coder should always be available
                coder = self.get_coder()
                try:
                    content = coder.io.read_text(abs_fname)
                    if coder.hashlines:
                        content = hashline(content)
                except Exception:
                    content = ""  # Empty content for unreadable files

                # Handle case where read_text returns None (file doesn't exist or has encoding errors)
                if content is None:
                    content = ""  # Empty content for unreadable files

            # Update cache
            self._file_contents_original[abs_fname] = content
            self._file_contents_snapshot[abs_fname] = content
            self._file_timestamps[abs_fname] = current_mtime

            # Clear previous diff
            self._file_diffs.pop(abs_fname, None)

        return self._file_contents_original.get(abs_fname, "")

    def get_file_content(
        self,
        fname: str,
        generate_stub: bool = False,
        context_management_enabled: bool = False,
        large_file_token_threshold: int = 8192,
    ) -> Optional[str]:
        """
        Get file content with optional stub generation for large files.

        This is a read-through cache: if file is not in cache, it will be read from disk.
        If generate_stub is True and file is large, returns a stub instead of full content.

        Args:
            fname: Absolute file path
            generate_stub: If True, generate stub for large files
            context_management_enabled: Whether context management is enabled
            large_file_token_threshold: Line count threshold for stub generation

        Returns:
            File content, stub for large files, or None if file cannot be read
        """
        abs_fname = os.path.abspath(fname)
        # First, ensure file is in cache (read-through cache)
        if abs_fname not in self._file_contents_original:
            self.add_file(fname)

        # Get content from cache
        content = self._file_contents_original.get(abs_fname)
        if content is None:
            return None

        # If not generating stub, return full content
        if not generate_stub:
            return content

        # If context management is not enabled, return full content
        if not context_management_enabled:
            return content

        coder = self.get_coder()

        # Check if file is large
        content_length = coder.main_model.token_count(content)

        if content_length <= large_file_token_threshold:
            return content

        # Use RepoMap to generate file stub
        return RepoMap.get_file_stub(fname, coder.io, line_numbers=True)

    def has_file_changed(self, fname: str) -> bool:
        """
        Check if file has been modified since last cache.

        Args:
            fname: Absolute file path

        Returns:
            True if file has changed
        """
        abs_fname = os.path.abspath(fname)

        if abs_fname not in self._file_contents_original:
            return True

        if not os.path.exists(abs_fname):
            return True

        current_mtime = os.path.getmtime(abs_fname)
        cached_mtime = self._file_timestamps.get(abs_fname, 0)

        return current_mtime > cached_mtime

    def generate_diff(self, fname: str) -> Optional[str]:
        """
        Generate diff between cached content and current file content.

        Args:
            fname: Absolute file path

        Returns:
            Unified diff string or None if no changes
        """
        abs_fname = os.path.abspath(fname)
        if abs_fname not in self._file_contents_original:
            return None

        # Read current content using coder.io.read_text()
        coder = self.get_coder()
        rel_fname = coder.get_rel_fname(fname)
        try:
            current_content = coder.io.read_text(abs_fname)
            if coder.hashlines:
                current_content = hashline(current_content)
        except Exception:
            return None

        # Check if current_content is None (file doesn't exist or can't be read)
        if current_content is None:
            return None

        # Get the last snapshot (use file cache as fallback for backward compatibility)
        snapshot_content = self._file_contents_snapshot.get(
            abs_fname, self._file_contents_original[abs_fname]
        )

        # Generate diff between snapshot and current content using hashline helper
        diff_text = get_hashline_content_diff(
            old_content=snapshot_content,
            new_content=current_content,
            fromfile=f"{rel_fname} (snapshot)",
            tofile=f"{rel_fname} (current)",
        )

        # If there's a diff, update the last snapshot with current content
        if diff_text.strip():
            self._file_contents_snapshot[abs_fname] = current_content

        return diff_text if diff_text.strip() else None

    def update_file_diff(self, fname: str) -> Optional[str]:
        """
        Update diff for file and add diff message to conversation.

        Args:
            fname: Absolute file path

        Returns:
            Diff string or None if no changes
        """
        coder = self.get_coder()
        diff = self.generate_diff(fname)

        if diff:
            # Store diff
            abs_fname = os.path.abspath(fname)
            self._file_diffs[abs_fname] = diff

            rel_fname = fname

            if coder:
                rel_fname = coder.get_rel_fname(fname)

            # Add diff message to conversation
            diff_message = {
                "role": "user",
                "content": (
                    f"{rel_fname} has been updated. Here is a git diff of the changes to"
                    f" review:\n\n{diff}"
                ),
            }

            ConversationService.get_manager(coder).add_message(
                message_dict=diff_message,
                tag=MessageTag.DIFFS,
                promotion=ConversationService.get_manager(coder).DEFAULT_TAG_PROMOTION_VALUE,
                mark_for_demotion=1,
            )

        return diff

    def get_file_stub(self, fname: str) -> str:
        """
        Get repository map stub for large files.

        This is a convenience method that calls get_file_content with stub generation enabled.

        Args:
            fname: Absolute file path

        Returns:
            Repository map stub or full content for small files
        """
        coder = self.get_coder()
        if not coder:
            return ""

        # Get context management settings from coder
        context_management_enabled = getattr(coder, "context_management_enabled", False)

        large_file_token_threshold = getattr(coder, "large_file_token_threshold", 8192)

        # Use the enhanced get_file_content method with stub generation
        content = self.get_file_content(
            fname=fname,
            generate_stub=True,
            context_management_enabled=context_management_enabled,
            large_file_token_threshold=large_file_token_threshold,
        )

        return content or ""

    def clear_file_cache(self, fname: Optional[str] = None) -> None:
        """
        Clear cache for specific file or all files.

        Args:
            fname: Optional specific file to clear (None = clear all)
        """
        if fname is None:
            self._file_contents_original.clear()
            self._file_contents_snapshot.clear()
            self._file_timestamps.clear()
            self._file_diffs.clear()
            self._file_to_message_id.clear()
            self._numbered_contexts.clear()
        else:
            abs_fname = os.path.abspath(fname)
            self._file_contents_original.pop(abs_fname, None)
            self._file_contents_snapshot.pop(abs_fname, None)
            self._file_timestamps.pop(abs_fname, None)
            self._file_diffs.pop(abs_fname, None)
            self._file_to_message_id.pop(abs_fname, None)
            self._image_files.pop(abs_fname, None)
            self._numbered_contexts.pop(abs_fname, None)

    def add_image_file(self, fname: str) -> None:
        """
        Track an image file.

        Args:
            fname: Absolute file path of image
        """
        abs_fname = os.path.abspath(fname)
        self._image_files[abs_fname] = True

    def remove_image_file(self, fname: str) -> None:
        """
        Remove an image file from tracking.

        Args:
            fname: Absolute file path of image
        """
        abs_fname = os.path.abspath(fname)
        self._image_files.pop(abs_fname, None)

    def get_all_tracked_files(self) -> set:
        """
        Get all tracked files (both regular and image files).

        Returns:
            Set of all tracked file paths
        """
        regular_files = set(self._file_contents_original.keys())
        image_files = set(self._image_files.keys())
        return regular_files.union(image_files)

    def update_file_context(
        self, file_path: str, start_line: int, end_line: int, auto_remove=True
    ) -> None:
        """
        Update numbered contexts for a file with a new range.

        Args:
            file_path: Absolute file path
            start_line: Start line number (1-based)
            end_line: End line number (1-based)
        """
        abs_fname = os.path.abspath(file_path)

        # Validate range
        if start_line > end_line:
            start_line, end_line = end_line, start_line

        # Get existing ranges
        existing_ranges = self._numbered_contexts.get(abs_fname, [])

        # Add new range
        new_range = (start_line, end_line)
        all_ranges = existing_ranges + [new_range]

        # Sort by start line
        all_ranges.sort(key=lambda x: x[0])

        # Merge overlapping or close ranges
        merged_ranges = []
        for current_start, current_end in all_ranges:
            if not merged_ranges:
                merged_ranges.append([current_start, current_end])
            else:
                last_start, last_end = merged_ranges[-1]

                # Check if ranges overlap or are close (within 20 lines)
                if current_start <= last_end + 20:  # Overlap or close
                    # Extend the range
                    merged_ranges[-1][1] = max(last_end, current_end)
                else:
                    # Add as new range
                    merged_ranges.append([current_start, current_end])

        # Convert back to tuples
        self._numbered_contexts[abs_fname] = [(start, end) for start, end in merged_ranges]

        # Remove using hash key (file_context, abs_fname)
        coder = self.get_coder()
        if coder and auto_remove:
            self.remove_file_messages(abs_fname)

    def get_file_context(self, file_path: str) -> str:
        """
        Generate hashline representation of cached context ranges.

        Args:
            file_path: Absolute file path

        Returns:
            Hashline representation of cached ranges, or empty string if no ranges
        """
        abs_fname = os.path.abspath(file_path)

        # Get cached ranges
        ranges = self._numbered_contexts.get(abs_fname, [])
        if not ranges:
            return ""

        # Get coder instance
        coder = self.get_coder()
        if not coder:
            return ""

        # Read file content
        try:
            content = coder.io.read_text(abs_fname)
            if not content:
                return ""
        except Exception:
            return ""

        # Generate hashline representations for each range
        context_parts = []
        for i, (start_line, end_line) in enumerate(ranges):
            # Note: hashline uses 1-based line numbers, so no conversion needed
            start_line_adj = max(1, start_line)
            end_line_adj = min(len(content.splitlines()), end_line)

            if start_line_adj > end_line_adj:
                continue

            # Extract lines for this range (0-based indexing for list)
            lines = content.splitlines()[start_line_adj - 1 : end_line_adj]

            # Generate hashline representation using the hashline() function
            # Join lines back with newlines for hashline()
            range_content = "\n".join(lines)
            hashline_content = hashline(range_content, start_line=start_line_adj)

            context_parts.append(hashline_content.strip())

        # Join with ellipsis separator
        return "\n...\n\n".join(context_parts)

    def remove_file_context(self, file_path: str) -> None:
        """
        Remove all cached context for a file.

        Args:
            file_path: Absolute file path
        """
        abs_fname = os.path.abspath(file_path)

        # Remove from numbered contexts
        self._numbered_contexts.pop(abs_fname, None)

        # Remove using hash key (file_context, abs_fname)
        coder = self.get_coder()
        if coder:
            ConversationService.get_manager(coder).remove_message_by_hash_key(
                ("file_context_user", abs_fname)
            )
            ConversationService.get_manager(coder).remove_message_by_hash_key(
                ("file_context_assistant", abs_fname)
            )

    def remove_file_messages(self, file_path: str) -> None:
        """
        Remove all file messages for a file path.

        Args:
            file_path: Absolute file path
        """
        abs_fname = os.path.abspath(file_path)

        # Remove using hash key (file_context, abs_fname)
        coder = self.get_coder()
        if coder:
            ConversationService.get_manager(coder).remove_message_by_hash_key(
                ("file_context_user", abs_fname)
            )
            ConversationService.get_manager(coder).remove_message_by_hash_key(
                ("file_context_assistant", abs_fname)
            )

    def clear_all_numbered_contexts(self) -> None:
        """Clear all numbered contexts for all files."""
        self._numbered_contexts.clear()

    def _get_numbered_contexts(self) -> Dict[str, List[Tuple[int, int]]]:
        """Get the numbered contexts dictionary."""
        return self._numbered_contexts

    def reset(self) -> None:
        """Clear all file caches and reset to initial state."""
        self.clear_file_cache()
        self.clear_all_numbered_contexts()
        self._initialized = False

    def debug_print_cache(self) -> None:
        """Print file cache contents and modification status."""
        print(f"File Cache ({len(self._file_contents_original)} files):")
        for fname, content in self._file_contents_original.items():
            mtime = self._file_timestamps.get(fname, 0)
            has_changed = self.has_file_changed(fname)
            status = "CHANGED" if has_changed else "CACHED"
            line_count = len(content.splitlines())

            # Check if snapshot differs from cache
            snapshot_content = self._file_contents_snapshot.get(fname)
            snapshot_differs = snapshot_content != content if snapshot_content else False
            snapshot_status = "DIFFERS" if snapshot_differs else "SAME"

            print(
                f"  {fname}: {status}, mtime={mtime}, "
                f"lines={line_count}, cached_len={len(content)}, snapshot={snapshot_status}"
            )

    def debug_get_cache_info(self) -> Dict[str, Any]:
        """Return dict with cache size, file count, and diff count."""
        # Count how many snapshots differ from their original cache
        snapshot_diff_count = 0
        for fname, cached_content in self._file_contents_original.items():
            snapshot_content = self._file_contents_snapshot.get(fname)
            if snapshot_content and snapshot_content != cached_content:
                snapshot_diff_count += 1

        return {
            "cache_size": len(self._file_contents_original),
            "snapshot_size": len(self._file_contents_snapshot),
            "snapshot_diff_count": snapshot_diff_count,
            "file_count": len(self._file_timestamps),
            "diff_count": len(self._file_diffs),
            "message_mappings": len(self._file_to_message_id),
        }
