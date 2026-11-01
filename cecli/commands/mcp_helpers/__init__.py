"""/mcp subcommand implementations.

The ``/list-mcp``, ``/load-mcp`` and ``/remove-mcp`` commands were consolidated
into ``/mcp <subcommand>``; these modules hold the per-subcommand logic so the
command class stays a thin dispatcher.
"""
