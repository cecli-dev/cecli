#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add the current directory to sys.path to allow importing from cecli
sys.path.append(os.getcwd())

from cecli.helpers.hashpos import HashPos  # noqa


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/get_hashline.py <file_path>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)

    try:
        content = file_path.read_text(encoding="utf-8")
        hashpos = HashPos(content)
        hashed_content = hashpos.format_content()
        print(hashed_content, end="")

        # Count duplicate hash position hashes
        lines = hashed_content.splitlines()
        hash_counts = {}
        for line in lines:
            if "|" in line:
                # Extract hash prefix between | characters
                parts = line.split("|", 2)
                if len(parts) >= 2:
                    hash_prefix = parts[1]
                    hash_counts[hash_prefix] = hash_counts.get(hash_prefix, 0) + 1

        # Find duplicates
        duplicates = {hash_prefix: count for hash_prefix, count in hash_counts.items() if count > 1}

        if duplicates:
            print(
                f"\n\nSummary: Found {len(duplicates)} duplicate hash position hashes:",
                file=sys.stderr,
            )
            for hash_prefix, count in sorted(duplicates.items()):
                print(f"  {hash_prefix}: {count} occurrences", file=sys.stderr)
        else:
            print("\n\nSummary: No duplicate hash position hashes found.", file=sys.stderr)

    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
