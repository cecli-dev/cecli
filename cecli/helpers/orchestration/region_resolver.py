"""
Region resolution helpers for the orchestration sandbox.

Provides AgentRegion for storing named region boundary *patterns* that are
resolved to content IDs on-demand at access time.  This ensures content IDs
are always fresh — important after intervening edits shift hashline positions.
"""

from __future__ import annotations

from typing import Any

from cecli.helpers.hashpos.transformations import (
    extract_hint,
    is_content_id,
    narrow_by_proximity,
    resolve_at_l,
    search_in_lines,
)


class AgentRegion:
    """
    Stores named region boundary *patterns* resolved to content IDs on access.

    Content IDs can shift after edits, so ``get_start(name)`` and
    ``get_end(name)`` re-read the file and re-resolve patterns at each call.
    Use these directly in ``EditFile`` calls for always-fresh IDs.

    When a region spec uses a **content ID** (e.g. `"—abcd—"`) instead of
    text, the referenced line content is snapshotted on first resolution.
    If the ID goes stale after intervening edits, subsequent resolutions
    fall back to content matching against the snapshotted line text.

    Example usage in orchestration code:

        regions = Agent.resolve_regions("foo.py", [
            {"name": "helper", "start": "def helper", "end": "return x"},
        ])
        edit_tool = Agent.get_tool("EditFile")
        await edit_tool.call(edits=[{
            "file_path": "foo.py",
            "operation": "replace",
            "start_line": regions.get_start("helper"),
            "end_line":   regions.get_end("helper"),
            "text": "def helper():\\n    return 42",
        }])
    """

    def __init__(
        self,
        file_path: str,
        coder: Any,
        region_specs: list[dict[str, str]],
        exact: bool = True,
    ) -> None:
        self._exact = exact
        self._file_path = file_path
        self._coder = coder
        self._specs: dict[str, dict[str, str]] = {}

        for spec in region_specs:
            name = spec["name"]
            entry: dict[str, object] = {
                "start": spec["start"],
                "end": spec["end"],
            }
            if "start_line_hint" in spec:
                entry["start_line_hint"] = spec["start_line_hint"]
            if "end_line_hint" in spec:
                entry["end_line_hint"] = spec["end_line_hint"]
            self._specs[name] = entry

        # Eagerly validate uniqueness for all regions at creation time.
        # This catches ambiguous patterns immediately with clear error messages.
        self._eager_validate()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_start(self, name: str) -> str:
        """Re-read file and return the current content ID for the start of *name*."""

        return self._resolve(name)[0]

    def get_end(self, name: str) -> str:
        """Re-read file and return the current content ID for the end of *name*."""

        return self._resolve(name)[1]

    def get_start_line(self, name: str) -> int:
        """Re-read file and return the current 1-based start line for *name*."""

        return self._resolve(name)[2]

    def get_end_line(self, name: str) -> int:
        """Re-read file and return the current 1-based end line for *name*."""

        return self._resolve(name)[3]

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def names(self) -> list[str]:
        """Return the list of region names."""

        return sorted(self._specs.keys())

    def get(self, name: str) -> dict[str, object]:
        """Return ``{"start": ..., "end": ..., "start_line": N, "end_line": N}`` for *name*.

        The returned dict can be passed directly as the ``region`` value
        in ``Agent.edit_region()`` edits.  ``start_line`` / ``end_line`` are
        1-based for readability and enable adjacent-edit detection.
        """

        start_id, end_id, start_line, end_line = self._resolve(name)
        return {
            "start": start_id,
            "end": end_id,
            "start_line": start_line + 1,
            "end_line": end_line + 1,
        }

    def __repr__(self) -> str:
        names = ", ".join(sorted(self._specs.keys()))
        return f"AgentRegion({len(self._specs)} regions on " f"{self._file_path!r}: {names})"

    # ------------------------------------------------------------------
    # Resolution internals
    # ------------------------------------------------------------------

    def _eager_validate(self) -> None:
        """Eagerly resolve and validate all region patterns at init time.

        Raises ValueError immediately for ambiguous patterns so the LLM
        gets clear feedback without waiting for the first access.
        """

        for name in list(self._specs.keys()):
            self._resolve(name)

    def _resolve(self, name: str) -> tuple[str, str, int, int]:
        """
        Re-read file and resolve *name* to
        (start_id, end_id, start_line, end_line).

        When a pattern is a content ID the referenced line is snapshotted
        so future resolutions can fall back to content matching if the
        original ID goes stale.
        """

        import os

        from cecli.helpers.hashline import (
            ContentHashError,
            normalize_hashline,
            resolve_content_to_hashline_ids,
        )
        from cecli.helpers.hashpos.hashpos import HashPos
        from cecli.tools.utils.helpers import resolve_paths

        spec = self._specs[name]

        # Read explicit line hints from spec (preferred over @L in patterns).
        # 1-based in the spec, converted to 0-based internally.
        explicit_start = spec.get("start_line_hint")
        explicit_end = spec.get("end_line_hint")

        abs_path, rel_path = resolve_paths(self._coder, self._file_path)

        if not os.path.isfile(abs_path):
            raise ValueError(f"File not found: {self._file_path}")

        content = self._coder.io.read_text(abs_path)

        if content is None:
            raise ValueError(f"Could not read file: {self._file_path}")

        lines = content.splitlines()
        hp = HashPos(content)

        start_pattern = self._resolve_pattern(
            hp, lines, spec, "start", normalize_hashline, ContentHashError
        )
        end_pattern = self._resolve_pattern(
            hp, lines, spec, "end", normalize_hashline, ContentHashError
        )

        # Always strip @L hints from patterns — they are metadata, not literal text.
        # Explicit hints (start_line_hint / end_line_hint) override any @L in patterns.
        start_pattern, extracted_start, start_hint_type = self._extract_l_hint(start_pattern, lines)
        end_pattern, extracted_end, end_hint_type = self._extract_l_hint(end_pattern, lines)

        # Handle explicit hints (start_line_hint / end_line_hint)
        # Integers are treated as @L (1-based line numbers).
        # Strings support the full @L, @A, @B syntax (same as ReadFile).
        if explicit_start is not None:
            if isinstance(explicit_start, str):
                # String hint — parse through _extract_l_hint
                _, start_hint, start_hint_type = self._extract_l_hint(explicit_start, lines)
                if start_hint is None:
                    # String hint like "@L394" may fail because the regex
                    # requires the @L to be preceded by whitespace or be at
                    # the start of the string. Guide the user to use an
                    # integer hint instead.
                    raise ValueError(
                        f"start_line_hint '{explicit_start}' for region "
                        f"'{name}' could not be resolved. "
                        f"Use an integer line number instead: "
                        f"start_line_hint={explicit_start.replace('@L', '')}"
                    )
            else:
                # Integer hint — treat as @L (1-based, converted to 0-based)
                start_hint = explicit_start - 1
                start_hint_type = "L"
        else:
            start_hint = extracted_start

        if explicit_end is not None:
            if isinstance(explicit_end, str):
                _, end_hint, end_hint_type = self._extract_l_hint(explicit_end, lines)
                if end_hint is None:
                    # String hint like "@L437" may fail because the regex
                    # requires @L to be preceded by whitespace or be at
                    # the start of the string. Guide the user to use an
                    # integer hint instead.
                    raise ValueError(
                        f"end_line_hint '{explicit_end}' for region "
                        f"'{name}' could not be resolved. "
                        f"Use an integer line number instead: "
                        f"end_line_hint={explicit_end.replace('@L', '')}"
                    )
            else:
                end_hint = explicit_end - 1
                end_hint_type = "L"
        else:
            end_hint = extracted_end

        # Strip hashline prefixes from text patterns — the LLM may have copied
        # content-ID-prefixed lines from a ReadFile response (e.g. —XYZ12—text).
        # Content-ID patterns and special markers are left untouched.
        if not self._looks_like_content_id(start_pattern) and start_pattern not in ("@000", "000@"):
            start_pattern = HashPos.strip_prefix(start_pattern)
        if not self._looks_like_content_id(end_pattern) and end_pattern not in ("@000", "000@"):
            end_pattern = HashPos.strip_prefix(end_pattern)

        # Validate uniqueness for text-based patterns (not content IDs or special markers).
        self._validate_pattern_uniqueness(
            start_pattern, start_hint, "start", name, lines, start_hint_type
        )
        self._validate_pattern_uniqueness(end_pattern, end_hint, "end", name, lines, end_hint_type)

        start_id, end_id = resolve_content_to_hashline_ids(
            content,
            start_pattern,
            end_pattern,
            start_hint_line=start_hint if start_hint_type == "L" else None,
            exact=self._exact,
        )

        # Resolve line numbers from content IDs
        def _line_from_id(content_id: str, default_if_not_found: int) -> int:
            if content_id == "@000":
                return 1

            if content_id == "000@":
                return len(lines)

            try:
                normalized = normalize_hashline(content_id)
                candidates = hp.resolve_to_lines(normalized)

                if candidates:
                    return candidates[0] + 1
            except (ContentHashError, ValueError):
                pass

            return default_if_not_found

        start_line = _line_from_id(start_id, -1)
        end_line = _line_from_id(end_id, -1)

        if start_line < 0 or end_line < 0:
            parts = []
            if start_line >= 0:
                parts.append(f"  Start pattern resolved to: {start_pattern!r} (line {start_line})")
            else:
                parts.append(f"  Start pattern NOT FOUND: {start_pattern!r}")
            if end_line >= 0:
                parts.append(f"  End pattern resolved to: {end_pattern!r} (line {end_line})")
            else:
                parts.append(f"  End pattern NOT FOUND: {end_pattern!r}")
            raise ValueError(
                f"Could not resolve line numbers for region "
                f"'{name}' in {self._file_path}\n" + "\n".join(parts)
            )

        return start_id, end_id, start_line, end_line

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _search_in_lines(lines: list[str], pattern: str) -> list[int]:
        """Return 0-based indices of all lines where *pattern* matches.

        Supports multiline patterns (each line of *pattern* must appear
        as a whole word in the corresponding line of *lines*).

        Delegates to the core ``search_in_lines`` in
        ``cecli.helpers.hashpos.transformations`` for unified matching.
        """

        return search_in_lines(lines, pattern)

    @staticmethod
    def _extract_l_hint(
        pattern: str, lines: list[str] | None = None
    ) -> tuple[str, int | None, str | None]:
        """Extract a hint suffix from a pattern string.

        Supports @L<num> (direct line number), @A{{regex}} (filter to matches AFTER
        the first regex match), and @B{{regex}} (filter to matches BEFORE the last
        regex match) hints.

        Returns (stripped_pattern, hint_value, hint_type) where:
          - hint_value is a 0-based line number or None
          - hint_type is 'L', 'A', 'B', or None
        """

        return extract_hint(pattern, lines)

    @staticmethod
    def _narrow_by_proximity(indices: list[int], target: int, max_results: int = 5) -> list[int]:
        """Return up to *max_results* indices closest to *target* (0-based)."""

        return narrow_by_proximity(indices, target, max_results=max_results)

    def _validate_pattern_uniqueness(
        self,
        pattern: str,
        hint: int | None,
        boundary: str,
        name: str,
        lines: list[str],
        hint_type: str | None = None,
    ) -> None:
        """Raise ValueError if *pattern* matches multiple locations.

        Only validates text patterns — content IDs and special markers
        (@000 / 000@) are inherently unique and are skipped.
        """

        if self._looks_like_content_id(pattern):
            return
        if pattern in ("@000", "000@"):
            return

        matches = self._search_in_lines(lines, pattern)

        # Apply @A/@B directional filtering — keep only closest match in direction
        if hint_type == "A" and hint is not None:
            after = [m for m in matches if m > hint]
            matches = [min(after)] if after else []
        elif hint_type == "B" and hint is not None:
            before = [m for m in matches if m < hint]
            matches = [max(before)] if before else []

        if len(matches) <= 1:
            return

        # Try proximity narrowing — find the unique closest match (only for @L hints)
        if hint is not None and hint_type == "L":
            best = min(matches, key=lambda i: abs(i - hint))
            best_dist = abs(best - hint)
            conflicts = [i for i in matches if i != best and abs(i - hint) == best_dist]
            if not conflicts:
                return  # Unique closest match found
            matches_for_display = [best] + conflicts
        else:
            matches_for_display = matches

        # Build detailed match display with line content
        max_preview = 10
        sorted_matches = sorted(matches_for_display)
        all_line_nums = [str(i + 1) for i in sorted_matches]
        line_nums_display = ", ".join(all_line_nums)
        if len(all_line_nums) > 50:
            line_nums_display = (
                ", ".join(all_line_nums[:50]) + f", ... ({len(all_line_nums)} total)"
            )

        # Only show content previews for the first 10 matches
        match_lines = []
        for i in sorted_matches[:max_preview]:
            line_content = lines[i]
            if len(line_content) > 120:
                line_content = line_content[:117] + "..."
            match_lines.append(f"  @L{i + 1}:    {line_content}")
        match_details = "\n".join(match_lines)
        if len(sorted_matches) > max_preview:
            match_details += f"\n  ... and {len(sorted_matches) - max_preview} more match(es)"

        if hint is not None:
            raise ValueError(
                f"{boundary.capitalize()} pattern '{pattern}' for region "
                f"'{name}' has {len(matches)} matches (lines {line_nums_display}); "
                f"@L{hint + 1} hint ties between "
                f"{len(matches_for_display)} equally-close locations:\n"
                f"{match_details}\n"
                f"Use a more specific pattern."
            )

        raise ValueError(
            f"{boundary.capitalize()} pattern '{pattern}' for region "
            f"'{name}' matches {len(matches)} locations (lines {line_nums_display}):\n"
            f"{match_details}\n"
            f"Use a more specific pattern or append ' @L<num>' to "
            f"disambiguate (e.g., '{pattern} @L{all_line_nums[0]}')."
        )

    @staticmethod
    def _looks_like_content_id(value: str) -> bool:
        """Return True if *value* appears to be a content ID rather than text."""

        return is_content_id(value)

    def _resolve_pattern(
        self,
        hp,
        lines: list[str],
        spec: dict[str, str],
        key: str,
        normalize_hashline,
        ContentHashError,
    ) -> str:
        """
        Resolve a single boundary pattern.

        Content-ID patterns have their referenced line content snapshotted
        so stale IDs can be recovered via content matching.
        """

        pattern = spec[key]

        # Special markers never go stale
        if pattern in ("@000", "000@"):
            return pattern

        # @L{num} notation — resolve via shared utility
        import re as _re

        _m = _re.match(r"^@L(\d+)$", pattern)
        if _m:
            return resolve_at_l(pattern, hp, lines)

        if not self._looks_like_content_id(pattern):
            return pattern

        # Content ID — try to resolve and snapshot the line content
        content_key = f"_{key}_content"

        try:
            normalized = normalize_hashline(pattern)
            candidates = hp.resolve_to_lines(normalized)

            if candidates and candidates[0] < len(lines):
                spec[content_key] = lines[candidates[0]]

                return pattern
        except (ContentHashError, ValueError):
            pass

        # Content ID may be stale — fall back to snapshotted line content
        cached = spec.get(content_key)

        if cached:
            return cached

        # No fallback available; return the (stale) ID and let the
        # caller's resolution logic handle the error
        return pattern
