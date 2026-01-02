#!/usr/bin/env python3
import argparse
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TokenUsage:
    """Store token usage and cost information."""

    sent: int
    received: int
    cost: float


def parse_token_line(line):
    """
    Parse a token usage line from cecli history.
    Example: "> Tokens: 12k sent, 133 received. Cost: $0.04 message, $0.10 session."
    """
    # fmt: off
    pattern = r">\s*Tokens:\s*(\d+(?:\.\d+)?k?)\s+sent,\s*(\d+(?:\.\d+)?k?)\s+received\.\s*Cost:\s*\$(\d+\.\d+)\s+message" # noqa
    # fmt: on

    match = re.search(pattern, line)
    if not match:
        return None

    # Parse sent tokens (handle 'k' suffix)
    sent_str = match.group(1)
    sent = int(float(sent_str.rstrip("k")) * 1000) if "k" in sent_str else int(sent_str)

    # Parse received tokens (handle 'k' suffix)
    received_str = match.group(2)
    received = (
        int(float(received_str.rstrip("k")) * 1000) if "k" in received_str else int(received_str)
    )

    # Parse cost
    cost = float(match.group(3))

    return TokenUsage(sent=sent, received=received, cost=cost)


def extract_costs(history_file):
    """Extract cost and token information from cecli history file."""
    usages = []

    with open(history_file, "r", encoding="utf-8") as f:
        for line in f:
            usage = parse_token_line(line)
            if usage:
                usages.append(usage)

    return usages


def main():
    parser = argparse.ArgumentParser(
        description="Calculate total cecli session costs from history files"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to analyze (default: current directory)",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="Search recursively in subdirectories"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed token usage per message"
    )

    args = parser.parse_args()

    # Convert to Path object
    target_dir = Path(args.directory)

    if not target_dir.exists():
        print(f"Error: Directory '{target_dir}' does not exist")
        return 1

    if not target_dir.is_dir():
        print(f"Error: '{target_dir}' is not a directory")
        return 1

    # Find all history files
    pattern = "**/.cecli*.history.md" if args.recursive else ".cecli*.history.md"
    history_files = list(target_dir.glob(pattern))

    if not history_files:
        print(f"No cecli history files found in '{target_dir}'")
        return 0

    total_cost = 0.0
    total_sent = 0
    total_received = 0

    print(f"Analyzing {len(history_files)} history file(s) in '{target_dir}':\n")

    for hist_file in sorted(history_files):
        usages = extract_costs(hist_file)

        if not usages:
            continue

        file_cost = sum(u.cost for u in usages)
        file_sent = sum(u.sent for u in usages)
        file_received = sum(u.received for u in usages)

        total_cost += file_cost
        total_sent += file_sent
        total_received += file_received

        # Show relative path for better readability
        rel_path = hist_file.relative_to(target_dir) if args.recursive else hist_file.name

        print(f"{rel_path}:")
        print(f"  Messages: {len(usages)}")
        print(f"  Tokens sent: {file_sent:,} | received: {file_received:,}")
        print(f"  Cost: ${file_cost:.4f}")

        if args.verbose:
            print("  Details:")
            for i, usage in enumerate(usages, 1):
                print(
                    f"    Message {i}: {usage.sent:,} sent, {usage.received:,} received →"
                    f" ${usage.cost:.4f}"
                )

        print()

    print(f"{'=' * 60}")
    print(f"Total tokens sent: {total_sent:,}")
    print(f"Total tokens received: {total_received:,}")
    print(f"Total cost: ${total_cost:.4f}")

    return 0


if __name__ == "__main__":
    exit(main())
