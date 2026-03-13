"""MCP server that exposes Solux workflows as tools for AI agent integration.

Each workflow is registered as an MCP tool. AI agents discover workflows via
``tools/list`` and invoke them via ``tools/call``.

Workflows that declare custom ``params:`` in their YAML are registered with
those parameter signatures. Workflows without custom params get the default
signature (source, mode, format, model) for backward compatibility.

Transport: stdio (standard for CLI-integrated MCP servers).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from solux.config import load_config
from solux.workflows.loader import list_workflows, load_workflow
from solux.workflows.engine import execute_workflow
from solux.workflows.models import Context, Workflow

logger = logging.getLogger("solux.mcp")


# Python type mapping for custom workflow params
_PARAM_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "bool": bool,
}


def _build_context(source: str, config: Any, params: dict[str, Any] | None = None) -> Context:
    """Build a workflow execution context from MCP tool arguments."""
    from solux.paths import compute_source_id

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


def _run_workflow_common(workflow_name: str, config: Any, params: dict[str, Any]) -> str:
    """Shared execution logic for both default and custom-param tools."""
    try:
        wf = load_workflow(workflow_name)
    except Exception as exc:
        return json.dumps({"error": f"Failed to load workflow '{workflow_name}': {exc}"})

    source = params.pop("source", "") or ""
    ctx = _build_context(source, config, params)
    ctx.data["runtime"] = {"no_cache": False, "verbose": False, "quiet_progress": True}

    try:
        result = execute_workflow(wf, ctx)
        output = _filter_output(result.data)
        return json.dumps(_make_serializable(output), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server with workflow tools."""
    mcp = FastMCP("solux")
    config = load_config()
    workflows, errors = list_workflows(interpolate_secrets=False, warn_missing_secrets=False)

    for err in errors:
        print(f"[solux mcp] warning: skipping invalid workflow: {err}", file=sys.stderr)

    for wf in workflows:
        if wf.params:
            _register_custom_tool(mcp, wf, config)
        else:
            _register_default_tool(mcp, wf.name, wf.description, config)

    return mcp


def _register_default_tool(mcp: FastMCP, name: str, description: str, config: Any) -> None:
    """Register a workflow with the default 4-param signature (backward compatible)."""
    tool_description = description or f"Run the '{name}' workflow."

    @mcp.tool(name=name, description=tool_description)
    async def run_workflow(
        source: str,
        mode: str = "full",
        format: str = "markdown",
        model: str | None = None,
    ) -> str:
        """Execute a Solux workflow.

        Args:
            source: Input source (URL or file path).
            mode: Summary mode (transcript, tldr, outline, notes, full).
            format: Output format (markdown, text, json).
            model: Override Ollama model for this run.
        """
        params: dict[str, Any] = {"source": source, "mode": mode, "format": format}
        if model:
            params["model"] = model
        return _run_workflow_common(name, config, params)


def _register_custom_tool(mcp: FastMCP, workflow: Workflow, config: Any) -> None:
    """Register a workflow with custom parameters declared in its YAML.

    Uses ``mcp.tool()`` with a dynamically constructed function whose
    signature matches the workflow's ``params:`` list.
    """
    import inspect

    wf_name = workflow.name
    tool_description = workflow.description or f"Run the '{wf_name}' workflow."

    # Build an inspect.Parameter list from the workflow's declared params
    sig_params: list[inspect.Parameter] = []
    for wp in workflow.params:
        py_type = _PARAM_TYPE_MAP.get(wp.type, str)
        if wp.required and wp.default is None:
            sig_params.append(
                inspect.Parameter(
                    wp.name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=py_type,
                )
            )
        else:
            default = wp.default
            # Coerce default to declared type
            if default is not None:
                try:
                    default = py_type(default)
                except (TypeError, ValueError):
                    pass
            sig_params.append(
                inspect.Parameter(
                    wp.name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=py_type | None if default is None else py_type,
                )
            )

    sig = inspect.Signature(sig_params)

    async def run_custom(**kwargs: Any) -> str:
        return _run_workflow_common(wf_name, config, dict(kwargs))

    # Attach the dynamic signature so FastMCP introspects correct params
    run_custom.__signature__ = sig  # type: ignore[attr-defined]
    run_custom.__name__ = wf_name
    run_custom.__doc__ = tool_description

    mcp.tool(name=wf_name, description=tool_description)(run_custom)


def run_mcp_server() -> None:
    """Start the MCP server over stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
        stream=sys.stderr,
    )
    server = create_mcp_server()
    server.run(transport="stdio")
