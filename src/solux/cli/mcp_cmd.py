"""CLI handler for ``solux mcp`` — start the MCP server over stdio."""

from __future__ import annotations

import argparse


def cmd_mcp(args: argparse.Namespace) -> int:
    """Start the MCP server over stdio for AI agent integration."""
    try:
        from solux.mcp.server import run_mcp_server
    except ImportError:
        import sys

        print(
            "MCP dependencies not installed. Install with: pip install 'solux[mcp]'",
            file=sys.stderr,
        )
        return 1

    run_mcp_server()
    return 0
