"""Tests for Phase 12: Web UI extensions."""

from __future__ import annotations

import html
import io
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from solus.serve.api import handle_list_workflows, handle_save_workflow, handle_trigger_webhook
from solus.serve.templates import (
    build_examples_page,
    build_history_page,
    build_modules_page,
    build_trigger_editor_page,
    build_triggers_page,
    build_workflow_editor_page,
    build_workflows_page,
    build_sse_script,
)


# --- Templates ---


def test_build_workflows_page_empty() -> None:
    page = build_workflows_page([], [])
    assert "Workflows" in page
    assert "New Workflow" in page
    assert 'data-active=true aria-current="page">Workflows' in page


def test_build_workflows_page_with_workflows() -> None:
    from solus.workflows.models import Step, Workflow

    wf = Workflow(
        name="my_workflow",
        description="A workflow",
        steps=[
            Step(name="step1", type="ai.llm_prompt"),
        ],
    )
    page = build_workflows_page([wf], [])
    assert "my_workflow" in page
    assert "A workflow" in page


def test_build_workflows_page_with_errors() -> None:
    page = build_workflows_page([], ["Error in workflow.yaml: bad YAML"])
    assert "Error" in page
    assert "bad YAML" in page


def test_build_workflow_editor_page_empty() -> None:
    page = build_workflow_editor_page("new_workflow", "", [])
    assert "new_workflow" in page
    assert "<textarea" in page
    assert "Save" in page


def test_build_workflow_editor_page_with_content() -> None:
    yaml_content = "name: test\ndescription: test wf\nsteps: []"
    page = build_workflow_editor_page("test", yaml_content, [])
    assert html.escape(yaml_content) in page or "name: test" in page


def test_build_workflow_editor_page_with_errors() -> None:
    page = build_workflow_editor_page("bad", "", ["Field X is required"])
    assert "Field X is required" in page


def test_build_triggers_page_has_restart_button() -> None:
    page = build_triggers_page([], [])
    assert "Restart Worker" in page
    assert 'action="/worker-restart"' in page
    assert 'name="next" value="/triggers"' in page
    assert 'data-active=true aria-current="page">Triggers' in page


def test_build_trigger_editor_page_has_restart_button() -> None:
    page = build_trigger_editor_page("daily_briefing_cron", "name: daily_briefing_cron\n", [])
    assert "Restart Worker" in page
    assert 'action="/worker-restart"' in page
    assert 'name="next" value="/trigger/daily_briefing_cron"' in page


def test_build_examples_page_has_separate_template_sections() -> None:
    page = build_examples_page(
        [{"name": "wf", "title": "WF", "description": "workflow", "yaml": "name: wf\n"}],
        [{"name": "tr", "title": "TR", "description": "trigger", "yaml": "name: tr\n"}],
    )
    assert 'class="template-section workflows"' in page
    assert 'class="template-section triggers"' in page
    assert 'class="section-split"' in page
    assert 'class="template-grid"' in page


def test_build_modules_page_empty() -> None:
    page = build_modules_page([])
    assert "Module Catalog" in page
    assert "<table" in page


def test_build_modules_page_with_spec() -> None:
    from solus.modules.spec import ModuleSpec, ContextKey

    def dummy(ctx, step):
        return ctx

    spec = ModuleSpec(
        name="test_mod",
        version="1.0.0",
        category="input",
        description="A test module",
        handler=dummy,
        writes=(ContextKey("my_key", "test"),),
    )
    page = build_modules_page([spec])
    assert "test_mod" in page
    assert "input" in page
    assert "A test module" in page
    assert "my_key" in page


def test_build_history_page_empty() -> None:
    page = build_history_page([])
    assert "History" in page
    assert "<table" in page


def test_build_history_page_with_jobs() -> None:
    jobs = [
        {
            "job_id": "abc123",
            "workflow_name": "audio_summary",
            "status": "done",
            "source": "https://example.com/audio.mp3",
            "created_at": "2024-01-15T10:00:00",
            "retry_count": 0,
        },
        {
            "job_id": "def456",
            "workflow_name": "webpage_summary",
            "status": "failed",
            "source": "https://example.com/page",
            "created_at": "2024-01-15T11:00:00",
            "retry_count": 2,
            "error": "Connection timeout",
        },
    ]
    page = build_history_page(jobs)
    assert "abc123" in page
    assert "audio_summary" in page
    assert "done" in page
    assert "def456" in page
    assert "failed" in page
    assert "Connection timeout" in page


def test_build_history_page_dead_letter() -> None:
    jobs = [
        {
            "job_id": "x",
            "workflow_name": "w",
            "status": "dead_letter",
            "source": "s",
            "created_at": "2024-01-01",
            "retry_count": 3,
        }
    ]
    page = build_history_page(jobs)
    assert "dead_letter" in page


def test_build_page_shows_dead_letter_count() -> None:
    from solus.serve.templates import build_page

    page = build_page(
        entries=[],
        selected_source=None,
        selected_file=None,
        file_content="<p>x</p>",
        queue_status={"pending": 0, "processing": 0, "done": 0, "failed": 0, "dead_letter": 2},
        recent_jobs=[],
        w_status={"status": "stopped", "pid": None},
        configured_workflows=["audio_summary", "webpage_summary"],
        configured_triggers=[("daily_briefing_cron", "trigger_event_note")],
    )
    assert "dead letter" in page
    assert ">2<" in page
    assert 'href="/workflows"' in page
    assert 'href="/triggers"' in page
    assert 'name="workflow"' in page
    assert "Configured workflows" in page
    assert "Configured triggers" in page
    assert "webpage_summary" in page
    assert "daily_briefing_cron" in page
    assert 'data-active=true aria-current="page">Solus' in page


def test_build_sse_script() -> None:
    script = build_sse_script()
    assert "EventSource" in script
    assert "/events" in script


# --- API: workflow management ---


def test_handle_list_workflows_returns_builtins() -> None:
    workflows, errors = handle_list_workflows()
    names = [wf.name for wf in workflows]
    assert len(workflows) > 0
    # audio_summary is a builtin
    assert "audio_summary" in names


def test_handle_save_workflow_valid(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    workflows_dir = tmp_path / "workflows"
    yaml_content = "name: test_wf\ndescription: A test\nsteps:\n  - name: s1\n    type: ai.llm_prompt\n    config: {}\n"
    ok, err = handle_save_workflow(cache_dir, workflows_dir, "test_wf", yaml_content)
    assert ok is True, f"Expected ok but got error: {err}"
    assert (workflows_dir / "test_wf.yaml").exists()


def test_handle_save_workflow_invalid_yaml(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    workflows_dir = tmp_path / "workflows"
    ok, err = handle_save_workflow(cache_dir, workflows_dir, "bad", "{ invalid yaml [")
    assert ok is False
    assert err


def test_handle_save_workflow_invalid_structure(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    workflows_dir = tmp_path / "workflows"
    # Valid YAML but missing required fields
    ok, err = handle_save_workflow(cache_dir, workflows_dir, "bad", "foo: bar\n")
    assert ok is False


def test_handle_save_workflow_invalid_name(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    workflows_dir = tmp_path / "workflows"
    ok, err = handle_save_workflow(cache_dir, workflows_dir, "bad name with spaces", "name: x")
    assert ok is False
    assert "Invalid workflow name" in err


def test_handle_save_workflow_empty_name(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    workflows_dir = tmp_path / "workflows"
    ok, err = handle_save_workflow(cache_dir, workflows_dir, "", "name: x")
    assert ok is False


# --- API: trigger webhook ---


def test_handle_trigger_webhook_queues_job(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    mock_wf = MagicMock()
    with patch("solus.workflows.loader.load_workflow", return_value=mock_wf):
        with patch("solus.workflows.registry.build_registry") as mock_registry:
            mock_registry.return_value = MagicMock()
            with patch("solus.workflows.validation.validate_workflow") as mock_validate:
                mock_validate.return_value = MagicMock(valid=True, issues=[])
                with patch("solus.serve.api.enqueue_jobs", return_value=[{"job_id": "test-job-1"}]):
                    ok, result = handle_trigger_webhook(cache_dir, "my_workflow", {"param": "value"})
    assert ok is True
    assert result["job_id"] == "test-job-1"
    assert result["status"] == "queued"


def test_handle_trigger_webhook_uses_explicit_workflows_dir(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    workflows_dir = tmp_path / "custom-workflows"
    workflows_dir.mkdir()
    (workflows_dir / "my_flow.yaml").write_text(
        "name: my_flow\ndescription: test\nsteps:\n  - name: s1\n    type: transform.text_clean\n    config: {}\n",
        encoding="utf-8",
    )

    with patch("solus.serve.api.enqueue_jobs", return_value=[{"job_id": "job-42"}]):
        ok, result = handle_trigger_webhook(
            cache_dir,
            "my_flow",
            {"source": "https://example.com"},
            workflows_dir=workflows_dir,
        )
    assert ok is True
    assert result["job_id"] == "job-42"


def test_handle_trigger_webhook_rejects_security_invalid_workflow(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    mock_wf = MagicMock()
    mock_cfg = MagicMock()
    mock_cfg.security.mode = "untrusted"
    with patch("solus.workflows.loader.load_workflow", return_value=mock_wf):
        with patch("solus.serve.api.enqueue_jobs", return_value=[{"job_id": "test-job-1"}]):
            with patch("solus.workflows.validation.validate_workflow") as mock_validate:
                mock_validate.return_value = MagicMock(
                    valid=False,
                    issues=[MagicMock(level="error", message="blocked in untrusted mode")],
                )
                ok, result = handle_trigger_webhook(
                    cache_dir,
                    "my_workflow",
                    {"param": "value"},
                    config=mock_cfg,
                )
    assert ok is False
    assert "security validation" in str(result)


def test_handle_trigger_webhook_invalid_workflow(tmp_path: Path) -> None:
    from solus.workflows.loader import WorkflowLoadError

    cache_dir = tmp_path / "cache"
    with patch("solus.workflows.loader.load_workflow", side_effect=WorkflowLoadError("not found")):
        ok, result = handle_trigger_webhook(cache_dir, "no_workflow", {})
    assert ok is False


def test_handle_trigger_webhook_rejects_invalid_workflow_name(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    ok, result = handle_trigger_webhook(cache_dir, "../etc-passwd", {})
    assert ok is False
    assert "Invalid workflow name" in str(result)


def test_handle_trigger_webhook_rejects_non_scalar_source(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    mock_wf = MagicMock()
    with patch("solus.workflows.loader.load_workflow", return_value=mock_wf):
        with patch("solus.workflows.registry.build_registry") as mock_registry:
            mock_registry.return_value = MagicMock()
            with patch("solus.workflows.validation.validate_workflow") as mock_validate:
                mock_validate.return_value = MagicMock(valid=True, issues=[])
                ok, result = handle_trigger_webhook(
                    cache_dir,
                    "my_workflow",
                    {"source": {"bad": "payload"}},
                )
    assert ok is False
    assert "Invalid 'source'" in str(result)


# --- HTTP handler routes ---


def test_handler_has_workflows_route(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler

    handler_class = build_handler(tmp_path, yt_dlp_binary=None)
    # Check that the handler class has the necessary methods
    handler_instance = handler_class.__new__(handler_class)
    assert hasattr(handler_instance, "_handle_workflows_list")
    assert hasattr(handler_instance, "_handle_workflow_editor")
    assert hasattr(handler_instance, "_handle_modules_catalog")
    assert hasattr(handler_instance, "_handle_history")
    assert hasattr(handler_instance, "_handle_sse")
    assert hasattr(handler_instance, "_handle_trigger_webhook")


def test_handler_build_accepts_config(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler

    # Should not raise even when config is provided
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=None)
    assert handler_class is not None


def test_handler_check_auth_no_config(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler

    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=None)
    handler = handler_class.__new__(handler_class)
    result = handler._check_auth()
    assert result is not None
    assert isinstance(result, dict)


def test_handler_check_auth_oidc_not_required(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler
    from solus.config import SecurityConfig

    mock_config = MagicMock()
    mock_config.security = SecurityConfig(oidc_require_auth=False)
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=mock_config)
    handler = handler_class.__new__(handler_class)
    result = handler._check_auth()
    assert result is not None
    assert isinstance(result, dict)


def test_handler_modules_catalog_uses_configured_modules_dir(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler
    from solus.serve.handler import _SYNTHETIC_ADMIN_CLAIMS

    mock_config = MagicMock()
    mock_config.modules_dir = tmp_path / "custom-modules"
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=mock_config)
    handler = handler_class.__new__(handler_class)
    handler._send_text = MagicMock()
    handler.headers = {}

    with patch("solus.modules.discovery.discover_modules", return_value=[]) as mock_discover:
        handler._handle_modules_catalog(dict(_SYNTHETIC_ADMIN_CLAIMS))

    mock_discover.assert_called_once_with(external_dir=mock_config.modules_dir)
    handler._send_text.assert_called()


def test_handler_workflow_route_rejects_invalid_name(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler

    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=None)
    handler = handler_class.__new__(handler_class)
    handler.path = "/workflow/../../secrets"
    handler.headers = {}
    handler._send_text = MagicMock()

    handler.do_GET()

    handler._send_text.assert_called_with("Invalid workflow name", status=400)


def test_handler_trigger_route_rejects_invalid_name(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler

    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=None)
    handler = handler_class.__new__(handler_class)
    handler.path = "/api/trigger/../../secrets"
    handler.headers = {"Content-Length": "0"}
    handler.rfile = io.BytesIO(b"")
    handler._send_json = MagicMock()

    handler.do_POST()

    handler._send_json.assert_called_with({"error": "Invalid workflow name"}, status=400)


# --- SSE endpoint ---


def test_build_sse_script_returns_string() -> None:
    script = build_sse_script()
    assert isinstance(script, str)
    assert len(script) > 0


def test_sse_script_has_event_source() -> None:
    script = build_sse_script()
    assert "EventSource" in script
    assert "/events" in script
    assert "pending-badge" in script


# ---------------------------------------------------------------------------
# H4: History pagination
# ---------------------------------------------------------------------------


def test_build_history_page_pagination_links(tmp_path: Path) -> None:
    """Page 2 of 5 should show Prev link and Next link."""
    page = build_history_page([], page=2, total_pages=5)
    assert "Page 2 of 5" in page
    assert "page=1" in page  # prev link
    assert "page=3" in page  # next link


def test_build_history_page_no_prev_on_first_page() -> None:
    page = build_history_page([], page=1, total_pages=3)
    assert "page=0" not in page  # no prev link on page 1
    assert "page=2" in page  # next link present


def test_build_history_page_no_next_on_last_page() -> None:
    page = build_history_page([], page=3, total_pages=3)
    assert "page=2" in page  # prev link present
    assert "page=4" not in page  # no next link on last page


def test_build_history_page_defaults_work() -> None:
    """Default call (no page/total_pages) should not raise."""
    page = build_history_page([])
    assert "History" in page
    assert "Page 1 of 1" in page


# ---------------------------------------------------------------------------
# M6: Bulk job operations
# ---------------------------------------------------------------------------


def test_build_history_page_has_bulk_buttons() -> None:
    page = build_history_page([])
    assert "bulk-retry-failed" in page
    assert "bulk-clear-dead" in page
    assert "Retry All Failed" in page
    assert "Clear Dead Letter" in page


def test_handle_bulk_retry_failed(tmp_path: Path) -> None:
    from solus.serve.api import handle_bulk_retry_failed

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    with patch("solus.serve.api.retry_failed_jobs", return_value=[{"job_id": "x"}]) as mock_retry:
        ok, msg = handle_bulk_retry_failed(cache_dir)
    assert ok is True
    assert "1" in msg
    mock_retry.assert_called_once_with(cache_dir)


def test_handle_bulk_clear_dead_letter(tmp_path: Path) -> None:
    from solus.serve.api import handle_bulk_clear_dead_letter

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    with patch("solus.serve.api.prune_jobs", return_value={"removed": 3, "remaining": 0}) as mock_prune:
        ok, msg = handle_bulk_clear_dead_letter(cache_dir)
    assert ok is True
    assert "3" in msg
    mock_prune.assert_called_once_with(cache_dir, statuses={"dead_letter"})


# ---------------------------------------------------------------------------
# M7: /healthz endpoint
# ---------------------------------------------------------------------------


def test_healthz_route_returns_json(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler

    handler_class = build_handler(tmp_path, yt_dlp_binary=None)
    handler = handler_class.__new__(handler_class)

    sent = {}

    def fake_send_json(data, status=200):
        sent["data"] = data
        sent["status"] = status

    handler._send_json = fake_send_json

    with patch(
        "solus.queueing.db_queue_counts",
        return_value={"pending": 1, "processing": 0, "done": 5, "failed": 0, "dead_letter": 0},
    ):
        handler._handle_healthz()

    assert sent["data"]["status"] == "ok"
    assert "queue" in sent["data"]
    assert sent.get("status", 200) == 200


def test_healthz_route_exists_before_auth(tmp_path: Path) -> None:
    """The /healthz route must be reachable without authentication."""
    from solus.serve.handler import build_handler

    handler_class = build_handler(tmp_path, yt_dlp_binary=None)
    handler = handler_class.__new__(handler_class)
    assert hasattr(handler, "_handle_healthz")


# ---------------------------------------------------------------------------
# H2: Rate limiter
# ---------------------------------------------------------------------------


def test_webhook_rate_limiter_allows_within_limit() -> None:
    from solus.serve.handler import _WebhookRateLimiter

    rl = _WebhookRateLimiter(max_per_minute=3)
    assert rl.allow("1.2.3.4") is True
    assert rl.allow("1.2.3.4") is True
    assert rl.allow("1.2.3.4") is True
    assert rl.allow("1.2.3.4") is False  # 4th request exceeds limit


def test_webhook_rate_limiter_independent_per_ip() -> None:
    from solus.serve.handler import _WebhookRateLimiter

    rl = _WebhookRateLimiter(max_per_minute=1)
    assert rl.allow("1.1.1.1") is True
    assert rl.allow("1.1.1.1") is False
    # Different IP is unaffected
    assert rl.allow("2.2.2.2") is True


def test_webhook_rate_limiter_compacts_stale_ips(monkeypatch) -> None:
    from solus.serve.handler import _WebhookRateLimiter

    now = {"t": 1000.0}
    monkeypatch.setattr("solus.serve.handler.time.monotonic", lambda: now["t"])

    rl = _WebhookRateLimiter(max_per_minute=2)
    assert rl.allow("1.1.1.1") is True
    assert "1.1.1.1" in rl._timestamps  # noqa: SLF001

    now["t"] += 61.0
    assert rl.allow("2.2.2.2") is True
    assert "1.1.1.1" not in rl._timestamps  # noqa: SLF001


def test_webhook_rate_limiter_bounds_tracked_ips() -> None:
    from solus.serve.handler import _WebhookRateLimiter

    rl = _WebhookRateLimiter(max_per_minute=1, max_tracked_ips=3)
    for idx in range(10):
        assert rl.allow(f"10.0.0.{idx}") is True
    assert len(rl._timestamps) <= 3  # noqa: SLF001
