"""Entry point for running the server as `python -m quintacle_core.mcp_server`
— stdio transport, matching the local-only design in docs/mcp-angle.md."""
from .server import main

main()
