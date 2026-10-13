"""Quintacle's MCP server — a second door onto the same stores the REST API
and frontend already use (see docs/mcp-angle.md). Every write here commits
immediately (no approval gate) and is staged first so it can be undone; see
`undo.py` and `ledger.py`."""
