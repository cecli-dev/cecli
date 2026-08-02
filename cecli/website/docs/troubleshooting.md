---
nav_order: 60
has_children: true
description: How to troubleshoot problems with cecli and get help.
---

# Troubleshooting

Below are some approaches for troubleshooting problems with cecli.

## Queue Commands

- **Queue not processing**: If queued prompts don't execute, ensure the system is idle (no active command running). Use `/list-queue` to verify prompts are in the queue.
- **Prompt not queued**: If `/queue` fails, check that the prompt is not empty, does not exceed 10,000 characters, and the queue is not full (100 items).
- **Cannot remove from queue**: Ensure you are using a valid positive integer index. Use `/list-queue` to verify current queue contents and valid indices.
- **Queue seems corrupted**: The queue is in-memory and session-specific. Restarting the CLI session will clear the queue.

## Queue Commands

- **Queue not processing**: Ensure the system is idle (no active command running). Use `/list-queue` to verify prompts are in the queue.
- **Prompt not queued**: Check if the prompt is empty, exceeds the 10,000 character limit, or if the queue is full (100 items).
- **Cannot remove from queue**: Ensure the index is a valid positive integer. Use `/list-queue` to verify current queue contents and valid indices.
- **Queue seems corrupted**: Restart the `cecli` session to clear the in-memory queue.

{% include help.md %}
