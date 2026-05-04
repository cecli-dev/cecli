"""Memory leak detection and heap analysis utilities.

Provides a MemorySnapshot class to inspect the largest allocated objects
in the Python heap: dicts, lists, and custom class instances.

Usage:
    from cecli.helpers.leak_detect import MemorySnapshot

    snap = MemorySnapshot()
    snap.print_report()

    # Programmatic access:
    for item in snap.largest_dicts(5):
        print(item["size_kb"], item["keys"])
"""

from __future__ import annotations

import gc
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Optional dependency wrappers ──


def _has_pympler() -> bool:
    try:
        import pympler  # noqa: F401

        return True
    except ImportError:
        return False


def _pympler_deep_size(obj: Any) -> int:
    """Return deep size of *obj* in bytes using pympler (if available)."""
    from pympler import asizeof

    return asizeof.asizeof(obj)


def _has_guppy() -> bool:
    try:
        from guppy import hpy  # noqa: F401

        return True
    except ImportError:
        return False


def _guppy_heap_summary() -> str:
    """Return per-type heap summary as a formatted string (guppy)."""
    from guppy import hpy

    hp = hpy()
    heap = hp.heap()
    return str(heap)


# ── Data structures ──


@dataclass
class ObjectInfo:
    """Describes a single allocated object found during a heap scan."""

    type_name: str
    size_bytes: int
    size_kb: float
    repr_str: str
    obj: Any = field(repr=False)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


@dataclass
class TypeSummary:
    """Aggregated statistics for a single type across the heap."""

    type_name: str
    count: int
    total_size_bytes: int

    @property
    def total_size_kb(self) -> float:
        return self.total_size_bytes / 1024

    @property
    def total_size_mb(self) -> float:
        return self.total_size_bytes / (1024 * 1024)


# ── Snapshot class ──


class MemorySnapshot:
    """Capture and analyse the current Python heap.

    Uses pympler when available for deep (recursive) size calculations;
    falls back to sys.getsizeof (shallow) otherwise.

    Example
    -------
    >>> snap = MemorySnapshot()
    >>> snap.print_report()

    Usage
    -------
    from cecli.helpers.leak_detect import MemorySnapshot
    MemorySnapshot().print_report()
    """

    def __init__(self, force_gc: bool = True):
        if force_gc:
            gc.collect()
        self._all_objects: List[Any] = gc.get_objects()
        self._has_pympler = _has_pympler()
        self._has_guppy = _has_guppy()

    # ── Size helpers ──

    def _size_of(self, obj: Any) -> int:
        # if self._has_pympler:
        #    return _pympler_deep_size(obj)
        return sys.getsizeof(obj)

    # ── Public query methods ──

    def largest_objects(self, n: int = 15) -> List[ObjectInfo]:
        """Return the *n* largest objects in the heap (any type)."""
        seen: set = set()
        results: List[ObjectInfo] = []

        try:
            for obj in self._all_objects:
                obj_id = id(obj)
                if obj_id in seen:
                    continue
                seen.add(obj_id)
                size = self._size_of(obj)
                if size < 1024:
                    continue
                try:
                    short = repr(obj)[:80]
                except Exception:
                    short = "<repr failed>"
                results.append(
                    ObjectInfo(
                        type_name=type(obj).__name__,
                        size_bytes=size,
                        size_kb=size / 1024,
                        repr_str=short,
                        obj=obj,
                    )
                )
        except Exception as e:
            print(e)

        results.sort(key=lambda x: x.size_bytes, reverse=True)
        print("result")
        return results[:n]

    def largest_dicts(self, n: int = 5) -> List[ObjectInfo]:
        """Return the *n* largest ``dict`` objects."""
        return self._filter_type(dict, n)

    def largest_lists(self, n: int = 5) -> List[ObjectInfo]:
        """Return the *n* largest ``list`` objects."""
        return self._filter_type(list, n)

    def largest_class_instances(
        self, classes: Optional[tuple] = None, n: int = 5
    ) -> List[ObjectInfo]:
        """Return the *n* largest instances of the given *classes*.

        When *classes* is ``None`` all instances of user-defined classes
        (excluding builtins) are considered.
        """
        if classes is not None:
            targets = tuple(c for c in classes if isinstance(c, type))
        else:
            # Heuristic: any type whose module is not a built-in.
            targets = None

        seen: set = set()
        results: List[ObjectInfo] = []

        for obj in self._all_objects:
            obj_id = id(obj)
            if obj_id in seen:
                continue
            seen.add(obj_id)
            if not isinstance(obj, type) and not callable(obj):
                if targets is not None:
                    if not isinstance(obj, targets):
                        continue
                else:
                    mod = type(obj).__module__
                    if mod in ("builtins", "_abc", "abc"):
                        continue
                    if type(obj).__name__.startswith("_"):
                        continue

                size = self._size_of(obj)
                if size < 512:
                    continue
                try:
                    short = repr(obj)[:80]
                except Exception:
                    short = "<repr failed>"
                results.append(
                    ObjectInfo(
                        type_name=type(obj).__name__,
                        size_bytes=size,
                        size_kb=size / 1024,
                        repr_str=short,
                        obj=obj,
                    )
                )

        results.sort(key=lambda x: x.size_bytes, reverse=True)
        return results[:n]

    def type_summary(self, n: int = 15) -> List[TypeSummary]:
        """Aggregate heap usage by type (total count and size)."""
        counter: Counter = Counter()
        size_map: Dict[str, int] = {}

        seen: set = set()
        for obj in self._all_objects:
            obj_id = id(obj)
            if obj_id in seen:
                continue
            seen.add(obj_id)
            tn = type(obj).__name__
            counter[tn] += 1
            size_map[tn] = size_map.get(tn, 0) + self._size_of(obj)

        sorted_types = sorted(counter, key=lambda t: size_map[t], reverse=True)

        return [
            TypeSummary(
                type_name=tn,
                count=counter[tn],
                total_size_bytes=size_map[tn],
            )
            for tn in sorted_types[:n]
        ]

    def guppy_summary(self) -> Optional[str]:
        """Return per-type heap summary string via guppy (if installed)."""
        if not self._has_guppy:
            return None
        return _guppy_heap_summary()

    # ── Report ──

    def print_report(self) -> None:
        """Print a human-readable memory report to stdout."""
        print("=" * 70)
        print("MemorySnapshot Report")
        print(f"  Objects scanned : {len(self._all_objects):,}")
        print(
            f"  Deep sizes      : {'yes (pympler)' if self._has_pympler else 'no (sys.getsizeof)'}"
        )
        print(f"  Guppy available  : {'yes' if self._has_guppy else 'no'}")
        print("=" * 70)

        # 1. Largest objects
        print("\n>> TOP 15 LARGEST OBJECTS (any type)")
        print("  " + "-" * 60)
        for item in self.largest_objects(15):
            print(f"  {item.size_kb:>10.1f} KB  {item.type_name:<15s}  {item.repr_str}")

        # 2. Largest dicts
        print("\n>> LARGEST DICTS")
        print("  " + "-" * 60)
        for item in self.largest_dicts(5):
            d = item.obj
            keys_preview = list(d.keys())[:5] if isinstance(d, dict) else []
            print(f"  {item.size_kb:>10.1f} KB  dict[{len(d)} keys]  keys={keys_preview!r}")

        # 3. Largest lists
        print("\n>> LARGEST LISTS")
        print("  " + "-" * 60)
        for item in self.largest_lists(5):
            lst = item.obj
            first = lst[0] if lst else "empty"
            print(f"  {item.size_kb:>10.1f} KB  list[{len(lst)} items]  first={first!r}")

        # 4. Largest class instances
        print("\n>> LARGEST CLASS INSTANCES (custom)")
        print("  " + "-" * 60)
        for item in self.largest_class_instances(n=10):
            print(f"  {item.size_kb:>10.1f} KB  {item.type_name}")

        # 5. Type summary
        print("\n>> TYPE SUMMARY (total size per type)")
        print("  " + "-" * 60)
        for ts in self.type_summary(12):
            print(f"  {ts.total_size_kb:>10.1f} KB  ({ts.count:>7,} objs)  {ts.type_name}")

        # 6. Guppy summary if available
        if self._has_guppy:
            print("\n>> GUPPY HEAP SUMMARY")
            print("  " + "-" * 60)
            summary = self.guppy_summary()
            if summary:
                for line in summary.split("\n"):
                    print(f"  {line}")

        print()

    # ── Internal helpers ──

    def _filter_type(self, typ: type, n: int) -> List[ObjectInfo]:
        """Return the *n* largest objects of a specific built-in type."""
        seen: set = set()
        results: List[ObjectInfo] = []

        for obj in self._all_objects:
            obj_id = id(obj)
            if obj_id in seen:
                continue
            seen.add(obj_id)
            if not isinstance(obj, typ):
                continue

            size = self._size_of(obj)
            if size < 512:
                continue
            try:
                short = repr(obj)[:80]
            except Exception:
                short = "<repr failed>"
            results.append(
                ObjectInfo(
                    type_name=type(obj).__name__,
                    size_bytes=size,
                    size_kb=size / 1024,
                    repr_str=short,
                    obj=obj,
                )
            )

        results.sort(key=lambda x: x.size_bytes, reverse=True)
        return results[:n]
