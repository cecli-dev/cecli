import json
import os
import weakref
from typing import Any, Dict, List, Optional, Tuple

import xxhash

from cecli.helpers.hashline import (
    get_hashline_content_diff,
    hashline_formatted,
)
from cecli.repomap import RepoMap

from .service import ConversationService
from .tags import MessageTag


class ConversationFiles:
    """
    Handles file content caching, change detection,
    and diff generation for file-based messages.
    """

    _instances = weakref.WeakKeyDictionary()  # coder -> ConversationFiles (ties lifetime)
    _uuid_index = weakref.WeakValueDictionary()  # uuid -> ConversationFiles (secondary lookup)

    def __init__(self, coder):
        self.coder = weakref.ref(coder)
        self.uuid = coder.uuid
        self._file_contents_original: Dict[str, str] = {}
        self._file_contents_snapshot: Dict[str, str] = {}
        self._file_json_contents: Dict[str, str] = {}
        self._file_timestamps: Dict[str, float] = {}
        self._file_diffs: Dict[str, str] = {}
        self._file_diff_versions: Dict[str, int] = {}
        self._file_context_versions: Dict[str, int] = {}
        self._file_stub_contents: Dict[str, str] = {}
        self._file_to_message_id: Dict[str, str] = {}
        self._image_files: Dict[str, bool] = {}
        self._numbered_contexts: Dict[str, List[Tuple[int, int]]] = {}
        self._last_merged_ranges: Dict[str, List[Tuple[int, int]]] = {}
        self._emitted_contexts: Dict[str, List[Tuple[int, int]]] = (
            {}
        )  # intervals already delivered as FILE_CONTEXTS
        self._initialized = True

    @classmethod
    def get_instance(cls, coder) -> "ConversationFiles":
        """Get or create files instance for coder."""
        # Fast path: exact coder object already registered
        if coder in cls._instances:
            return cls._instances[coder]

        # Fallback: child coder inheriting parent's uuid
        if coder.uuid in cls._uuid_index:
            instance = cls._uuid_index[coder.uuid]

            if instance.get_coder() is not coder:
                instance.coder = weakref.ref(coder)

            cls._instances[coder] = instance

            return instance

        # New coder with a new uuid — create fresh
        instance = cls(coder)
        cls._instances[coder] = instance
        cls._uuid_index[coder.uuid] = instance
        return instance

    @classmethod
    def destroy_instance(cls, coder_uuid: str):
        """Explicit cleanup for sub-agents."""
        if coder_uuid in cls._uuid_index:
            instance = cls._uuid_index[coder_uuid]
            # Remove from coder-keyed dict
            for key, val in list(cls._instances.items()):
                if val is instance:
                    del cls._instances[key]
                    break
            del cls._uuid_index[coder_uuid]

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
                    content = coder.io.read_text(abs_fname, silent=True)
                    if coder.hashlines:
                        content, json_str = hashline_formatted(content, file_name=abs_fname)
                        self._file_json_contents[abs_fname] = json_str
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

        # Use RepoMap to generate file stub (with read-through cache)
        if abs_fname not in self._file_stub_contents:
            self._file_stub_contents[abs_fname] = RepoMap.get_file_stub(
                fname, coder.io, line_numbers=True
            )

        return self._file_stub_contents[abs_fname]

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
            current_content = coder.io.read_text(abs_fname, silent=True)
            if coder.hashlines:
                current_content, _ = hashline_formatted(current_content, file_name=abs_fname)
        except Exception:
            return None

        # Check if current_content is None (file doesn't exist or can't be read)
        if current_content is None:
            return None

        # Get the last snapshot (use file cache as fallback for backward compatibility)
        snapshot_content = self._file_contents_snapshot.get(
            abs_fname, self._file_contents_original[abs_fname]
        )

        if not snapshot_content:
            self.add_file(abs_fname, content=current_content)
            return None

        # Generate diff between snapshot and current content using hashline helper
        diff_text = get_hashline_content_diff(
            old_content=snapshot_content,
            new_content=current_content,
            fromfile=f"{rel_fname} (snapshot)",
            tofile=f"{rel_fname} (current)",
            context_lines=3,
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
        diff_output = diff

        if diff:
            # Increment diff version counter
            abs_fname = os.path.abspath(fname)
            self._file_diff_versions[abs_fname] = self._file_diff_versions.get(abs_fname, 0) + 1

            # Store diff
            self._file_diffs[abs_fname] = diff

            rel_fname = fname
            prefix_str = ""

            if coder:
                rel_fname = coder.get_rel_fname(fname)
                prefix_str = "content ID prefixed " if getattr(coder, "hashlines") else ""

            if coder.hashlines:
                # Wrap diff in JSON structure
                diff_output = json.dumps(
                    {
                        "file_name": rel_fname,
                        "prefixed_diff": diff,
                    },
                    ensure_ascii=False,
                )

            # Add diff message to conversation
            content_hash = xxhash.xxh3_128_hexdigest(diff.encode("utf-8"))

            diff_message = {
                "role": "user",
                "content": (
                    f"{rel_fname} has been updated. Review this {prefix_str}diff of the changes to"
                    f" ensure all modifications are appropriate:\n\n{diff_output}"
                ),
            }

            ConversationService.get_manager(coder).add_message(
                message_dict=diff_message,
                tag=MessageTag.DIFFS,
                hash_key=("file_diff_user", rel_fname, content_hash),
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

    def get_file_json(self, fname: str) -> Optional[str]:
        """
        Get the cached JSON metadata for a file, if available.

        The JSON is generated and cached during add_file() and contains
        file_name, start_line, end_line, partial, and prefixed_contents.

        Args:
            fname: Absolute file path

        Returns:
            JSON-formatted string, or None if not cached
        """
        abs_fname = os.path.abspath(fname)
        return self._file_json_contents.get(abs_fname)

    def clear_file_cache(self, fname: Optional[str] = None, clear_contexts=True) -> None:
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
            self._file_diff_versions.clear()
            self._file_context_versions.clear()
            self._file_stub_contents.clear()
            self._file_json_contents.clear()
            self._file_to_message_id.clear()
            self._emitted_contexts.clear()
            if clear_contexts:
                self._numbered_contexts.clear()
        else:
            abs_fname = os.path.abspath(fname)
            self._file_contents_original.pop(abs_fname, None)
            self._file_contents_snapshot.pop(abs_fname, None)
            self._file_timestamps.pop(abs_fname, None)
            self._file_diffs.pop(abs_fname, None)
            self._file_diff_versions.pop(abs_fname, None)
            self._file_context_versions.pop(abs_fname, None)
            self._file_stub_contents.pop(abs_fname, None)
            self._file_json_contents.pop(abs_fname, None)
            self._file_to_message_id.pop(abs_fname, None)
            self._image_files.pop(abs_fname, None)
            self._emitted_contexts.pop(abs_fname, None)
            if clear_contexts:
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
    ) -> Tuple[int, int]:
        """
        Update numbered contexts for a file with a new range.

        Args:
            file_path: Absolute file path
            start_line: Start line number (1-based)
            end_line: End line number (1-based)

        Returns:
            The merged range (start_line, end_line) that contains the input range.
        """
        abs_fname = os.path.abspath(file_path)
        diff_version = self._file_diff_versions.get(abs_fname, 0)
        context_version = self._file_context_versions.get(abs_fname, 0)

        # Validate range
        if start_line > end_line:
            start_line, end_line = end_line, start_line

        # Get existing ranges
        existing_ranges = self._numbered_contexts.get(abs_fname, [])

        if diff_version != context_version:
            self._file_context_versions[abs_fname] = diff_version
            # Content changed: force re-emission of context (stale blocks won't
            # refresh otherwise).
            self._emitted_contexts.pop(abs_fname, None)
        # existing_ranges = []

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

                # Check if new range overlaps/contains with the last range
                # (since sorted by start, this means current_start is between last_start and last_end)
                if current_start <= last_end:  # Overlap or adjacent
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

        # Find the merged range that contains the input range
        for merged_start, merged_end in self._numbered_contexts[abs_fname]:
            if merged_start <= start_line and merged_end >= end_line:
                return (merged_start, merged_end)

        return (start_line, end_line)  # fallback

    def push_range(self, file_path: str, ranges: List[Tuple[int, int]]) -> None:
        """
        Push merged ranges into the _last_merged_ranges cache for a file.

        Args:
            file_path: Absolute file path
            ranges: List of (start_line, end_line) tuples, as returned by
                update_file_context()
        """
        abs_fname = os.path.abspath(file_path)
        if abs_fname not in self._last_merged_ranges:
            self._last_merged_ranges[abs_fname] = []
        self._last_merged_ranges[abs_fname].extend(ranges)
        # Deduplicate and sort by start_line
        self._last_merged_ranges[abs_fname] = sorted(
            set(self._last_merged_ranges[abs_fname]),
            key=lambda x: x[0],
        )

    def clear_ranges(self, file_path: Optional[str] = None) -> None:
        """
        Clear the _last_merged_ranges cache for a specific file or all files.

        Args:
            file_path: Optional absolute file path (None = clear all)
        """
        if file_path is None:
            self._last_merged_ranges.clear()
        else:
            abs_fname = os.path.abspath(file_path)
            self._last_merged_ranges.pop(abs_fname, None)

    def get_file_context(self, file_path: str, all_ranges=False, check_versions=True) -> str:
        """
        Generate hashline representation of cached context ranges.

        Args:
            file_path: Absolute file path

        Returns:
            JSON-formatted string with file_path, version, and results array,
            or empty string if no ranges
        """
        abs_fname = os.path.abspath(file_path)

        # Get cached ranges - prefer _last_merged_ranges over full _numbered_contexts
        ranges = self._last_merged_ranges.get(abs_fname, []) or self._numbered_contexts.get(
            abs_fname, []
        )

        if all_ranges:
            ranges = self._numbered_contexts.get(abs_fname, [])

        if not ranges:
            return ""

        # Get coder instance
        coder = self.get_coder()
        if not coder:
            return ""

        # Read file content
        try:
            content = coder.io.read_text(abs_fname, silent=True)
            if not content:
                return ""
        except Exception:
            return ""

        # Generate hashline representations for each range
        results = []
        content_lines = content.splitlines()
        diff_version = self._file_diff_versions.get(abs_fname, 0)
        context_version = self._file_context_versions.get(abs_fname, 0)

        for i, (start_line, end_line) in enumerate(ranges):
            # Note: hashline uses 1-based line numbers, so no conversion needed
            start_line_adj = max(1, start_line)
            end_line_adj = min(len(content_lines), end_line)

            if start_line_adj > end_line_adj:
                continue

            # Extract lines for this range (0-based indexing for list)
            lines = content_lines[start_line_adj - 1 : end_line_adj]

            # Generate JSON for this range using hashline_formatted()
            range_content = "\n".join(lines)

            # Don't duplicate whole contents that are already in context
            if (
                check_versions
                and range_content == content
                and (abs_fname in coder.abs_fnames or abs_fname in coder.abs_read_only_fnames)
                and diff_version == context_version
            ):
                continue

            # Hash the full content first so that adjacent-line hashes
            # are computed with proper surrounding context from the complete
            # file, then extract only the range's lines. This ensures content
            # IDs are consistent with other tools (e.g., ReadFile) that hash
            # the full file content.
            full_prefixed, _ = hashline_formatted(
                content,
                file_name=abs_fname,
                total_lines=len(content_lines),
                start_line=1,
            )
            prefixed_lines = full_prefixed.splitlines()
            range_prefixed_lines = prefixed_lines[start_line_adj - 1 : end_line_adj]
            range_prefixed_content = "\n".join(range_prefixed_lines)

            json_str = json.dumps(
                {
                    "file_name": abs_fname,
                    "start_line": start_line_adj,
                    "end_line": end_line_adj,
                    "total_lines": len(content_lines),
                    "prefixed_contents": range_prefixed_content,
                },
                ensure_ascii=False,
            )
            results.append(json.loads(json_str))

        # Build and return the top-level JSON structure
        # version = self._file_diff_versions.get(abs_fname, 0)
        if results:
            result = {
                "file_path": file_path,
                "results": results,
                # "version": version,
            }
            return json.dumps(result, ensure_ascii=False)

        return None

    def get_new_file_context(self, file_path: str) -> str:
        """Return hashline content for ranges NOT yet emitted as FILE_CONTEXTS.

        Append-only delta: only genuinely-new line ranges are emitted against
        the previously-emitted intervals, so overlapping reads don't re-send
        content already in the conversation. Nothing is removed, so the
        conversation stays an append-only log.
        """
        abs_fname = os.path.abspath(file_path)
        current = sorted(self._numbered_contexts.get(abs_fname, []))
        if not current:
            return ""
        emitted = sorted(self._emitted_contexts.get(abs_fname, []))
        delta = _subtract_intervals(current, emitted)
        if not delta:
            return ""
        rendered = self._render_context_ranges(abs_fname, delta)
        if not rendered:
            return ""
        # Mark everything currently requested as emitted so future reads only
        # emit the overlap-free remainder.
        self._emitted_contexts[abs_fname] = current
        return rendered

    def _render_context_ranges(self, abs_fname: str, ranges: List[Tuple[int, int]]) -> str:
        """Render hashline content for the given 1-based line ranges. Returns JSON or ''."""
        coder = self.get_coder()
        if not coder:
            return ""
        try:
            content = coder.io.read_text(abs_fname, silent=True)
            if not content:
                return ""
        except Exception:
            return ""
        content_lines = content.splitlines()
        results = []
        for start_line, end_line in ranges:
            start_line_adj = max(1, start_line)
            end_line_adj = min(len(content_lines), end_line)
            if start_line_adj > end_line_adj:
                continue
            # Hash the full file so adjacent-line hashes are consistent with ReadFile.
            full_prefixed, _ = hashline_formatted(
                content,
                file_name=abs_fname,
                total_lines=len(content_lines),
                start_line=1,
            )
            prefixed_lines = full_prefixed.splitlines()
            range_prefixed_lines = prefixed_lines[start_line_adj - 1 : end_line_adj]
            range_prefixed_content = "\n".join(range_prefixed_lines)
            json_str = json.dumps(
                {
                    "file_name": abs_fname,
                    "start_line": start_line_adj,
                    "end_line": end_line_adj,
                    "total_lines": len(content_lines),
                    "prefixed_contents": range_prefixed_content,
                },
                ensure_ascii=False,
            )
            results.append(json.loads(json_str))
        if results:
            return json.dumps({"file_path": abs_fname, "results": results}, ensure_ascii=False)
        return ""

    def remove_file_context(self, file_path: str) -> None:
        """
        Remove all cached context for a file.

        Args:
            file_path: Absolute file path
        """
        abs_fname = os.path.abspath(file_path)

        # Remove from numbered contexts
        self._numbered_contexts.pop(abs_fname, None)

        # Remove using hash key pattern matching for file_context messages
        coder = self.get_coder()
        if coder:
            ConversationService.get_manager(coder).remove_messages_by_hash_key_pattern(
                lambda hash_key: (
                    isinstance(hash_key, tuple)
                    and len(hash_key) in (2, 3)
                    and hash_key[0] in ("file_context_user", "file_context_assistant")
                    and hash_key[1] == abs_fname
                )
            )

    def remove_file_messages(self, file_path: str) -> None:
        """
        Remove all file messages for a file path.

        Args:
            file_path: Absolute file path
        """
        abs_fname = os.path.abspath(file_path)

        # Remove using hash key pattern matching for file_context messages
        coder = self.get_coder()
        if coder:
            ConversationService.get_manager(coder).remove_messages_by_hash_key_pattern(
                lambda hash_key: (
                    isinstance(hash_key, tuple)
                    and len(hash_key) in (2, 3)
                    and hash_key[0] in ("file_context_user", "file_context_assistant")
                    and hash_key[1] == abs_fname
                )
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
        self.clear_ranges()
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


def _subtract_intervals(
    base: List[Tuple[int, int]], remove: List[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Return the portions of ``base`` not covered by ``remove``.

    Both inputs are lists of inclusive, disjoint, 1-based ``(start, end)``
    intervals already sorted by start line. Used to compute the append-only
    FILE_CONTEXTS delta (only genuinely-new ranges are emitted).
    """
    remaining = []
    for a, b in base:
        parts = [(a, b)]
        for r0, r1 in remove:
            new_parts = []
            for s, e in parts:
                if e < r0 or s > r1:
                    new_parts.append((s, e))
                else:
                    if s < r0:
                        new_parts.append((s, r0 - 1))
                    if e > r1:
                        new_parts.append((r1 + 1, e))
            parts = new_parts
        remaining.extend(parts)
    return remaining
