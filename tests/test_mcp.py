"""Tests for the MCP server module.

These test the MCP integration layer, not workflow execution itself.
External dependencies (Ollama, etc.) are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    import mcp  # noqa: F401

    _has_mcp = True
except ImportError:
    _has_mcp = False

_requires_mcp = pytest.mark.skipif(not _has_mcp, reason="mcp package not installed")


@pytest.fixture
def mock_config(tmp_path: Path):
    """Create a minimal config for testing."""
    config = MagicMock()
    config.paths = MagicMock()
    config.paths.cache_dir = tmp_path / "cache"
    config.paths.cache_dir.mkdir(parents=True, exist_ok=True)
    config.security = MagicMock()
    config.security.mode = "trusted"
    config.ollama = MagicMock()
    config.ollama.model = "qwen3:8b"
    config.ollama.base_url = "http://localhost:11434"
    return config


@pytest.fixture
def sample_workflows():
    """Return a list of sample workflow objects for testing."""
    from solus.workflows.models import Step, Workflow, WorkflowParam

    return [
        Workflow(
            name="webpage_summary",
            description="Fetch a webpage and summarize its content.",
            steps=[
                Step(name="fetch", type="input.webpage_fetch", config={}),
                Step(name="summarize", type="ai.llm_summarize", config={}),
            ],
        ),
        Workflow(
            name="audio_summary",
            description="Download, transcribe, and summarize audio.",
            steps=[
                Step(name="fetch", type="input.source_fetch", config={}),
                Step(name="transcribe", type="ai.whisper_transcribe", config={}),
                Step(name="summarize", type="ai.llm_summarize", config={}),
            ],
        ),
        Workflow(
            name="custom_search",
            description="Search with custom params.",
            steps=[Step(name="search", type="input.source_fetch", config={})],
            params=[
                WorkflowParam(name="query", type="str", required=True, description="Search query"),
                WorkflowParam(name="count", type="int", default=5, description="Result count"),
            ],
        ),
    ]


@_requires_mcp
class TestMCPServerCreation:
    """Test MCP server initialization and tool registration."""

    @patch("solus.mcp.server.load_config")
    @patch("solus.mcp.server.list_workflows")
    def test_create_mcp_server_registers_tools(self, mock_list_wf, mock_load_cfg, mock_config, sample_workflows):
        mock_load_cfg.return_value = mock_config
        mock_list_wf.return_value = (sample_workflows, [])

        from solus.mcp.server import create_mcp_server

        server = create_mcp_server()
        assert server is not None
        # The server should have been created with the name "solus"
        assert server.name == "solus"

    @patch("solus.mcp.server.load_config")
    @patch("solus.mcp.server.list_workflows")
    def test_create_mcp_server_handles_invalid_workflows(self, mock_list_wf, mock_load_cfg, mock_config):
        mock_load_cfg.return_value = mock_config
        mock_list_wf.return_value = ([], ["Error loading broken.yaml: invalid YAML"])

        from solus.mcp.server import create_mcp_server

        # Should not raise despite errors
        server = create_mcp_server()
        assert server is not None

    @patch("solus.mcp.server.load_config")
    @patch("solus.mcp.server.list_workflows")
    def test_create_mcp_server_empty_workflows(self, mock_list_wf, mock_load_cfg, mock_config):
        mock_load_cfg.return_value = mock_config
        mock_list_wf.return_value = ([], [])

        from solus.mcp.server import create_mcp_server

        server = create_mcp_server()
        assert server is not None


@_requires_mcp
class TestHelperFunctions:
    """Test internal helper functions."""

    def test_filter_output_removes_internal_keys(self):
        from solus.mcp.server import _filter_output

        data = {
            "output_text": "Hello world",
            "sentiment": "positive",
            "_step_timings": [{"name": "fetch", "duration_ms": 100}],
            "_item": "foo",
            "_index": 0,
            "runtime": {"no_cache": False},
        }
        result = _filter_output(data)
        assert "output_text" in result
        assert "sentiment" in result
        assert "runtime" in result
        assert "_step_timings" not in result
        assert "_item" not in result
        assert "_index" not in result

    def test_filter_output_empty_dict(self):
        from solus.mcp.server import _filter_output

        assert _filter_output({}) == {}

    def test_make_serializable_handles_basic_types(self):
        from solus.mcp.server import _make_serializable

        assert _make_serializable("hello") == "hello"
        assert _make_serializable(42) == 42
        assert _make_serializable(3.14) == 3.14
        assert _make_serializable(True) is True
        assert _make_serializable(None) is None

    def test_make_serializable_handles_nested_structures(self):
        from solus.mcp.server import _make_serializable

        data = {"key": [1, 2, {"nested": "value"}]}
        result = _make_serializable(data)
        assert result == {"key": [1, 2, {"nested": "value"}]}

    def test_make_serializable_converts_non_serializable(self):
        from solus.mcp.server import _make_serializable

        result = _make_serializable(Path("/some/path"))
        assert isinstance(result, str)
        assert "/some/path" in result

    def test_build_context(self, mock_config):
        from solus.mcp.server import _build_context

        ctx = _build_context("https://example.com", mock_config, {"mode": "full"})
        assert ctx.source == "https://example.com"
        assert ctx.source_id  # should be a non-empty hash
        assert ctx.data == {}
        assert ctx.params == {"mode": "full"}

    def test_build_context_default_params(self, mock_config):
        from solus.mcp.server import _build_context

        ctx = _build_context("test.txt", mock_config)
        assert ctx.params == {}

    def test_build_context_with_custom_params(self, mock_config):
        from solus.mcp.server import _build_context

        ctx = _build_context("https://example.com", mock_config, {"query": "test", "count": 5})
        assert ctx.params["query"] == "test"
        assert ctx.params["count"] == 5


@_requires_mcp
class TestCustomToolRegistration:
    """Test registration of workflows with custom params."""

    @patch("solus.mcp.server.load_config")
    @patch("solus.mcp.server.list_workflows")
    def test_server_registers_custom_param_workflow(self, mock_list_wf, mock_load_cfg, mock_config, sample_workflows):
        mock_load_cfg.return_value = mock_config
        mock_list_wf.return_value = (sample_workflows, [])

        from solus.mcp.server import create_mcp_server

        server = create_mcp_server()
        assert server is not None

    def test_run_workflow_common_returns_error_for_missing_workflow(self, mock_config):
        from solus.mcp.server import _run_workflow_common

        result = _run_workflow_common("nonexistent_workflow", mock_config, {})
        assert "error" in json.loads(result)


class TestMCPCLI:
    """Test the CLI command handler."""

    def test_cmd_mcp_missing_dependency(self, monkeypatch):
        """When mcp is not installed, cmd_mcp should return 1."""
        import solus.cli.mcp_cmd as mcp_mod

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "solus.mcp.server":
                raise ImportError("No module named 'mcp'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        # Re-import to get fresh module
        import importlib

        importlib.reload(mcp_mod)

        args = MagicMock()
        result = mcp_mod.cmd_mcp(args)
        assert result == 1

        # Restore
        monkeypatch.setattr("builtins.__import__", original_import)

    def test_mcp_in_parser_commands(self):
        """Verify 'mcp' is a recognized subcommand."""
        from solus.cli.parser import build_parser

        parser = build_parser()
        # Should parse without error
        args = parser.parse_args(["mcp"])
        assert args.command == "mcp"

    def test_mcp_in_cli_commands_set(self):
        """Verify 'mcp' is in the recognized commands set."""
        from solus.cli import parse_args

        args = parse_args(["mcp"])
        assert args.command == "mcp"
