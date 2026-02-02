import difflib
import os
import weakref
from typing import Any, Dict, Optional

from cecli.repomap import RepoMap

from .manager import ConversationManager
from .tags import MessageTag


class ConversationFiles:
    """
    Singleton class that handles file content caching, change detection,
    and diff generation for file-based messages.

    Design: Singleton class with static methods, not requiring initialization.
    """

    # Class-level storage for singleton pattern
    _file_contents_original: Dict[str, str] = {}
    _file_contents_snapshot: Dict[str, str] = {}
    _file_timestamps: Dict[str, float] = {}
    _file_diffs: Dict[str, str] = {}
    _file_to_message_id: Dict[str, str] = {}
    # Track image files separately since they don't have text content
    _image_files: Dict[str, bool] = {}
    _coder_ref = None
    _initialized = False

    @classmethod
    def initialize(cls, coder) -> None:
        """
        Set up singleton with weak reference to coder.

        Args:
            coder: The coder instance to reference
        """
        cls._coder_ref = weakref.ref(coder)
        cls._initialized = True

    @classmethod
    def add_file(
        cls,
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

        if force_refresh or abs_fname not in cls._file_contents_original:
            # Read content from disk if not provided
            if content is None:
                # Use coder.io.read_text() - coder should always be available
                coder = cls.get_coder()
                try:
                    content = coder.io.read_text(abs_fname)
                except Exception:
                    content = ""  # Empty content for unreadable files

                # Handle case where read_text returns None (file doesn't exist or has encoding errors)
                if content is None:
                    content = ""  # Empty content for unreadable files

            # Update cache
            cls._file_contents_original[abs_fname] = content
            cls._file_contents_snapshot[abs_fname] = content
            cls._file_timestamps[abs_fname] = current_mtime

            # Clear previous diff
            cls._file_diffs.pop(abs_fname, None)

        return cls._file_contents_original.get(abs_fname, "")

    @classmethod
    def get_file_content(
        cls,
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
        if abs_fname not in cls._file_contents_original:
            cls.add_file(fname)

        # Get content from cache
        content = cls._file_contents_original.get(abs_fname)
        if content is None:
            return None

        # If not generating stub, return full content
        if not generate_stub:
            return content

        # If context management is not enabled, return full content
        if not context_management_enabled:
            return content

        coder = cls.get_coder()

        # Check if file is large
        content_length = coder.main_model.token_count(content)

        if content_length <= large_file_token_threshold:
            return content

        # Use RepoMap to generate file stub
        return RepoMap.get_file_stub(fname, coder.io, line_numbers=True)

    @classmethod
    def has_file_changed(cls, fname: str) -> bool:
        """
        Check if file has been modified since last cache.

        Args:
            fname: Absolute file path

        Returns:
            True if file has changed
        """
        abs_fname = os.path.abspath(fname)

        if abs_fname not in cls._file_contents_original:
            return True

        if not os.path.exists(abs_fname):
            return True

        current_mtime = os.path.getmtime(abs_fname)
        cached_mtime = cls._file_timestamps.get(abs_fname, 0)

        return current_mtime > cached_mtime

    @classmethod
    def generate_diff(cls, fname: str) -> Optional[str]:
        """
        Generate diff between cached content and current file content.

        Args:
            fname: Absolute file path

        Returns:
            Unified diff string or None if no changes
        """
        abs_fname = os.path.abspath(fname)
        if abs_fname not in cls._file_contents_original:
            return None

        # Read current content using coder.io.read_text()
        coder = cls.get_coder()
        rel_fname = coder.get_rel_fname(fname)
        try:
            current_content = coder.io.read_text(abs_fname)
        except Exception:
            return None

        # Check if current_content is None (file doesn't exist or can't be read)
        if current_content is None:
            return None

        # Get the last snapshot (use file cache as fallback for backward compatibility)
        snapshot_content = cls._file_contents_snapshot.get(
            abs_fname, cls._file_contents_original[abs_fname]
        )

        # Generate diff between snapshot and current content
        diff_lines = difflib.unified_diff(
            snapshot_content.splitlines(),
            current_content.splitlines(),
            fromfile=f"{rel_fname} (snapshot)",
            tofile=f"{rel_fname} (current)",
            lineterm="",
            n=3,
        )

        diff_text = "\n".join([line for line in list(diff_lines)])

        # If there's a diff, update the last snapshot with current content
        if diff_text.strip():
            cls._file_contents_snapshot[abs_fname] = current_content

        return diff_text if diff_text.strip() else None

    @classmethod
    def update_file_diff(cls, fname: str) -> Optional[str]:
        """
        Update diff for file and add diff message to conversation.

        Args:
            fname: Absolute file path

        Returns:
            Diff string or None if no changes
        """
        coder = cls.get_coder()
        diff = cls.generate_diff(fname)

        if diff:
            # Store diff
            abs_fname = os.path.abspath(fname)
            cls._file_diffs[abs_fname] = diff

            rel_fname = fname

            if coder:
                rel_fname = coder.get_rel_fname(fname)

            # Add diff message to conversation
            diff_message = {
                "role": "user",
                "content": f"File {rel_fname} has changed:\n\n{diff}",
            }

            if coder and hasattr(coder, "abs_fnames"):
                tag = (
                    MessageTag.EDIT_FILES
                    if abs_fname in coder.abs_fnames
                    else MessageTag.CHAT_FILES
                )
            else:
                tag = MessageTag.CHAT_FILES

            ConversationManager.add_message(
                message_dict=diff_message,
                tag=tag,
            )

        return diff

    @classmethod
    def get_file_stub(cls, fname: str) -> str:
        """
        Get repository map stub for large files.

        This is a convenience method that calls get_file_content with stub generation enabled.

        Args:
            fname: Absolute file path

        Returns:
            Repository map stub or full content for small files
        """
        coder = cls.get_coder()
        if not coder:
            return ""

        # Get context management settings from coder
        context_management_enabled = getattr(coder, "context_management_enabled", False)

        large_file_token_threshold = getattr(coder, "large_file_token_threshold", 8192)

        # Use the enhanced get_file_content method with stub generation
        content = cls.get_file_content(
            fname=fname,
            generate_stub=True,
            context_management_enabled=context_management_enabled,
            large_file_token_threshold=large_file_token_threshold,
        )

        return content or ""

    @classmethod
    def clear_file_cache(cls, fname: Optional[str] = None) -> None:
        """
        Clear cache for specific file or all files.

        Args:
            fname: Optional specific file to clear (None = clear all)
        """
        if fname is None:
            cls._file_contents_original.clear()
            cls._file_contents_snapshot.clear()
            cls._file_timestamps.clear()
            cls._file_diffs.clear()
            cls._file_to_message_id.clear()
        else:
            abs_fname = os.path.abspath(fname)
            cls._file_contents_original.pop(abs_fname, None)
            cls._file_contents_snapshot.pop(abs_fname, None)
            cls._file_timestamps.pop(abs_fname, None)
            cls._file_diffs.pop(abs_fname, None)
            cls._file_to_message_id.pop(abs_fname, None)
            cls._image_files.pop(abs_fname, None)

    @classmethod
    def add_image_file(cls, fname: str) -> None:
        """
        Track an image file.

        Args:
            fname: Absolute file path of image
        """
        abs_fname = os.path.abspath(fname)
        cls._image_files[abs_fname] = True

    @classmethod
    def remove_image_file(cls, fname: str) -> None:
        """
        Remove an image file from tracking.

        Args:
            fname: Absolute file path of image
        """
        abs_fname = os.path.abspath(fname)
        cls._image_files.pop(abs_fname, None)

    @classmethod
    def get_all_tracked_files(cls) -> set:
        """
        Get all tracked files (both regular and image files).

        Returns:
            Set of all tracked file paths
        """
        regular_files = set(cls._file_contents_original.keys())
        image_files = set(cls._image_files.keys())
        return regular_files.union(image_files)

    @classmethod
    def get_coder(cls):
        """Get current coder instance via weak reference."""
        if cls._coder_ref:
            return cls._coder_ref()
        return None

    @classmethod
    def reset(cls) -> None:
        """Clear all file caches and reset to initial state."""
        cls.clear_file_cache()
        cls._coder_ref = None
        cls._initialized = False

    # Debug methods
    @classmethod
    def debug_print_cache(cls) -> None:
        """Print file cache contents and modification status."""
        print(f"File Cache ({len(cls._file_contents_original)} files):")
        for fname, content in cls._file_contents_original.items():
            mtime = cls._file_timestamps.get(fname, 0)
            has_changed = cls.has_file_changed(fname)
            status = "CHANGED" if has_changed else "CACHED"
            line_count = len(content.splitlines())

            # Check if snapshot differs from cache
            snapshot_content = cls._file_contents_snapshot.get(fname)
            snapshot_differs = snapshot_content != content if snapshot_content else False
            snapshot_status = "DIFFERS" if snapshot_differs else "SAME"

            print(
                f"  {fname}: {status}, mtime={mtime}, "
                f"lines={line_count}, cached_len={len(content)}, snapshot={snapshot_status}"
            )

    @classmethod
    def debug_get_cache_info(cls) -> Dict[str, Any]:
        """Return dict with cache size, file count, and diff count."""
        # Count how many snapshots differ from their original cache
        snapshot_diff_count = 0
        for fname, cached_content in cls._file_contents_original.items():
            snapshot_content = cls._file_contents_snapshot.get(fname)
            if snapshot_content and snapshot_content != cached_content:
                snapshot_diff_count += 1

        return {
            "cache_size": len(cls._file_contents_original),
            "snapshot_size": len(cls._file_contents_snapshot),
            "snapshot_diff_count": snapshot_diff_count,
            "file_count": len(cls._file_timestamps),
            "diff_count": len(cls._file_diffs),
            "message_mappings": len(cls._file_to_message_id),
        }
