"""MCP server that exposes Solus workflows as tools for AI agent integration.

Each workflow is registered as an MCP tool. AI agents discover workflows via
``tools/list`` and invoke them via ``tools/call``.

Transport: stdio (standard for CLI-integrated MCP servers).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from solus.config import load_config
from solus.workflows.loader import list_workflows, load_workflow
from solus.workflows.engine import execute_workflow
from solus.workflows.models import Context

logger = logging.getLogger("solus.mcp")


def _build_context(source: str, config: Any, params: dict[str, Any] | None = None) -> Context:
    """Build a workflow execution context from MCP tool arguments."""
    from solus.paths import compute_source_id

    sid = compute_source_id(source)
    return Context(
        source=source,
        source_id=sid,
        data={},
        config=config,
        logger=logger,
        params=params or {},
    )


def _filter_output(data: dict[str, Any]) -> dict[str, Any]:
    """Filter out internal keys (prefixed with ``_``) from context data."""
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _make_serializable(obj: Any) -> Any:
    """Convert non-serializable objects to strings for JSON output."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server with workflow tools."""
    mcp = FastMCP("solus")
    config = load_config()
    workflows, errors = list_workflows(interpolate_secrets=False, warn_missing_secrets=False)

    for err in errors:
        print(f"[solus mcp] warning: skipping invalid workflow: {err}", file=sys.stderr)

    for wf in workflows:
        _register_workflow_tool(mcp, wf.name, wf.description, config)

    return mcp


def _register_workflow_tool(mcp: FastMCP, name: str, description: str, config: Any) -> None:
    """Register a single workflow as an MCP tool."""
    tool_description = description or f"Run the '{name}' workflow."

    @mcp.tool(name=name, description=tool_description)
    async def run_workflow(
        source: str,
        mode: str = "full",
        format: str = "markdown",
        model: str | None = None,
    ) -> str:
        """Execute a Solus workflow.

        Args:
            source: Input source (URL or file path).
            mode: Summary mode (transcript, tldr, outline, notes, full).
            format: Output format (markdown, text, json).
            model: Override Ollama model for this run.
        """
        workflow_name = name  # capture from closure
        try:
            wf = load_workflow(workflow_name)
        except Exception as exc:
            return json.dumps({"error": f"Failed to load workflow '{workflow_name}': {exc}"})

        run_config = config
        if model:
            # Override model in a copy of config's ollama section
            if hasattr(run_config, "ollama") and hasattr(run_config.ollama, "model"):
                # Config is frozen, so we set the model via params instead
                pass

        params: dict[str, Any] = {"mode": mode, "format": format}
        if model:
            params["model"] = model

        ctx = _build_context(source, run_config, params)
        ctx.data["runtime"] = {"no_cache": False, "verbose": False, "quiet_progress": True}

        try:
            result = execute_workflow(wf, ctx)
            output = _filter_output(result.data)
            return json.dumps(_make_serializable(output), indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # Each registration needs a unique function, but the decorator returns
    # the same wrapper; the name= parameter on @mcp.tool handles uniqueness.


def run_mcp_server() -> None:
    """Start the MCP server over stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
        stream=sys.stderr,
    )
    server = create_mcp_server()
    server.run(transport="stdio")
