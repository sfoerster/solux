"""Tests for JSON content negotiation and RBAC enforcement in handler.py."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest

from solux.audit import AuditLogger
from solux.serve import _build_handler


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def server(tmp_path: Path):
    """Start a test HTTP server with JSON API support and audit logging."""
    from http.server import ThreadingHTTPServer

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    # Create queue directory for audit DB
    queue_dir = cache_dir / "queue"
    queue_dir.mkdir()

    audit_logger = AuditLogger(cache_dir, enabled=True)

    handler_cls = _build_handler(
        cache_dir,
        yt_dlp_binary=None,
        audit_logger=audit_logger,
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    class Info:
        def __init__(self):
            self.cache_dir = cache_dir
            self.port = port
            self.httpd = httpd
            self.audit_logger = audit_logger

    info = Info()
    yield info
    httpd.shutdown()


def _get_json(port: int, path: str) -> tuple[int, dict]:
    """Make a GET request with Accept: application/json."""
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", path, headers={"Accept": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(data)
    except json.JSONDecodeError:
        return resp.status, {"_raw": data.decode("utf-8", errors="replace")}


def _get_html(port: int, path: str) -> tuple[int, bytes]:
    """Make a GET request without JSON Accept header (HTML response)."""
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def _post_json(
    port: int,
    path: str,
    body: str = "",
    *,
    content_type: str = "application/x-www-form-urlencoded",
) -> tuple[int, dict]:
    """Make a POST request with Accept: application/json."""
    conn = HTTPConnection("127.0.0.1", port)
    headers = {"Accept": "application/json", "Content-Type": content_type}
    conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(data)
    except json.JSONDecodeError:
        return resp.status, {"_raw": data.decode("utf-8", errors="replace")}


# ── JSON content negotiation on GET endpoints ────────────────────────────


class TestJSONContentNegotiation:
    def test_healthz_returns_json(self, server) -> None:
        status, data = _get_json(server.port, "/healthz")
        assert status == 200
        assert "status" in data
        assert data["status"] == "ok"
        assert "queue" in data

    def test_index_returns_json(self, server) -> None:
        status, data = _get_json(server.port, "/")
        assert status == 200
        assert "queue" in data
        assert "workflow_count" in data
        assert "worker" in data
        assert "recent_jobs" in data
        assert "user" in data

    def test_index_user_info(self, server) -> None:
        """Dashboard JSON should include user identity and roles."""
        status, data = _get_json(server.port, "/")
        assert status == 200
        user = data["user"]
        assert user["identity"] == "admin"  # synthetic admin claims
        assert "admin" in user["roles"]
        assert user["highest_role"] == "admin"

    def test_index_html_fallback(self, server) -> None:
        """Without Accept: application/json, should return HTML."""
        status, data = _get_html(server.port, "/")
        assert status == 200
        assert b"<" in data  # Should contain HTML tags

    def test_workflows_json(self, server) -> None:
        status, data = _get_json(server.port, "/workflows")
        assert status == 200
        assert "workflows" in data
        assert isinstance(data["workflows"], list)

    def test_triggers_json(self, server) -> None:
        status, data = _get_json(server.port, "/triggers")
        assert status == 200
        assert "triggers" in data
        assert isinstance(data["triggers"], list)

    def test_history_json(self, server) -> None:
        status, data = _get_json(server.port, "/history")
        assert status == 200
        assert "jobs" in data
        assert "page" in data
        assert "total_pages" in data
        assert "total" in data

    def test_history_pagination(self, server) -> None:
        status, data = _get_json(server.port, "/history?page=1")
        assert status == 200
        assert data["page"] == 1

    def test_config_json(self, server) -> None:
        status, data = _get_json(server.port, "/config")
        assert status == 200
        assert "path" in data
        assert "content" in data

    def test_modules_json(self, server) -> None:
        status, data = _get_json(server.port, "/modules")
        assert status == 200
        assert "modules" in data
        assert isinstance(data["modules"], list)

    def test_examples_json(self, server) -> None:
        status, data = _get_json(server.port, "/examples")
        assert status == 200
        assert "workflows" in data
        assert "triggers" in data

    def test_worker_status_json(self, server) -> None:
        status, data = _get_json(server.port, "/worker-status")
        assert status == 200
        # worker-status always returns JSON regardless of Accept header

    def test_workflow_detail_json(self, server) -> None:
        status, data = _get_json(server.port, "/workflow/new")
        assert status == 200
        assert "name" in data
        assert "yaml" in data
        assert "steps" in data

    def test_workflow_detail_json_includes_parsed_steps(self, server) -> None:
        """Existing workflow JSON response should include parsed steps."""
        status, data = _get_json(server.port, "/workflow/audio_summary")
        assert status == 200
        assert "name" in data
        assert "yaml" in data
        assert "steps" in data
        assert isinstance(data["steps"], list)
        # audio_summary is a built-in workflow with known steps
        assert len(data["steps"]) > 0
        step = data["steps"][0]
        assert "name" in step
        assert "type" in step

    def test_workflow_detail_json_includes_meta(self, server) -> None:
        """Workflow JSON response should include meta field."""
        status, data = _get_json(server.port, "/workflow/new")
        assert status == 200
        assert "meta" in data
        # new workflow has no meta
        assert data["meta"] == {}

    def test_workflow_detail_meta_from_yaml(self, tmp_path) -> None:
        """Workflow with a meta block should have it in the JSON response."""
        from http.server import ThreadingHTTPServer

        cache_dir = tmp_path / "cache_meta"
        cache_dir.mkdir()
        (cache_dir / "queue").mkdir()
        wf_dir = cache_dir / "workflows.d"
        wf_dir.mkdir()

        (wf_dir / "meta_test_wf.yaml").write_text(
            "name: meta_test_wf\n"
            "meta:\n"
            "  manual_estimate_minutes: 45\n"
            "  manual_estimate_label: Manual triage\n"
            "steps:\n"
            "  - name: step1\n"
            "    type: transform.text_clean\n"
            "    config:\n"
            "      input_key: raw_text\n"
            "      output_key: cleaned_text\n"
        )

        audit_logger = AuditLogger(cache_dir, enabled=True)
        handler_cls = _build_handler(
            cache_dir,
            yt_dlp_binary=None,
            workflows_dir=wf_dir,
            audit_logger=audit_logger,
        )
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        port = httpd.server_address[1]
        from threading import Thread

        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        try:
            status, data = _get_json(port, "/workflow/meta_test_wf")
            assert status == 200
            assert "meta" in data
            assert data["meta"]["manual_estimate_minutes"] == 45
            assert data["meta"]["manual_estimate_label"] == "Manual triage"
        finally:
            httpd.shutdown()

    def test_trigger_detail_json(self, server) -> None:
        status, data = _get_json(server.port, "/trigger/new")
        assert status == 200
        assert "name" in data
        assert "yaml" in data

    def test_not_found_json(self, server) -> None:
        status, data = _get_json(server.port, "/nonexistent")
        assert status == 404

    def test_job_detail_not_found(self, server) -> None:
        status, data = _get_json(server.port, "/api/job/nonexistent123")
        assert status == 404
        assert data.get("error") == "Job not found"

    def test_job_detail_invalid_id(self, server) -> None:
        status, data = _get_json(server.port, "/api/job/../../etc")
        assert status == 400
        assert "Invalid" in data.get("error", "")

    def test_job_detail_returns_job(self, server) -> None:
        from solux.queueing import enqueue_jobs

        created = enqueue_jobs(server.cache_dir, ["test.pdf"], workflow_name="clinical_doc_triage")
        job_id = created[0]["job_id"]

        status, data = _get_json(server.port, f"/api/job/{job_id}")
        assert status == 200
        assert data["job_id"] == job_id
        assert data["workflow_name"] == "clinical_doc_triage"
        assert data["status"] == "pending"

    def test_job_detail_includes_context(self, server) -> None:
        from solux.queueing import enqueue_jobs, update_job
        from solux.paths import source_dir

        created = enqueue_jobs(server.cache_dir, ["ctx-test.pdf"], workflow_name="test_wf")
        job_id = created[0]["job_id"]
        sid = "ctxtest111"
        update_job(server.cache_dir, job_id, status="done", source_id=sid)

        # Write context.json in the source dir
        sdir = source_dir(server.cache_dir, sid)
        (sdir / "context.json").write_text(json.dumps({"doc_type": "lab_result", "summary": "All normal"}))

        status, data = _get_json(server.port, f"/api/job/{job_id}")
        assert status == 200
        assert data.get("context") is not None
        assert data["context"]["doc_type"] == "lab_result"
        assert data["context"]["summary"] == "All normal"

    def test_job_detail_includes_result_files(self, server) -> None:
        from solux.queueing import enqueue_jobs, update_job
        from solux.paths import source_dir

        created = enqueue_jobs(server.cache_dir, ["files-test.pdf"], workflow_name="test_wf")
        job_id = created[0]["job_id"]
        sid = "filestest222"
        update_job(server.cache_dir, job_id, status="done", source_id=sid)

        sdir = source_dir(server.cache_dir, sid)
        (sdir / "summary-full.md").write_text("# Summary")
        (sdir / "context.json").write_text('{"k": "v"}')

        status, data = _get_json(server.port, f"/api/job/{job_id}")
        assert status == 200
        assert "result_files" in data
        names = [f["name"] for f in data["result_files"]]
        assert "summary-full.md" in names
        assert "context.json" in names


# ── Audit API ────────────────────────────────────────────────────────────


class TestAuditAPI:
    def test_audit_query_empty(self, server) -> None:
        status, data = _get_json(server.port, "/api/audit")
        assert status == 200
        assert "events" in data
        assert "total" in data
        assert data["events"] == []

    def test_audit_query_with_events(self, server) -> None:
        # Log some events directly
        server.audit_logger.log(action="test.action", identity="test-user")
        server.audit_logger.log(action="test.action2", identity="test-user")

        status, data = _get_json(server.port, "/api/audit")
        assert status == 200
        assert len(data["events"]) == 2
        assert data["total"] == 2

    def test_audit_query_with_filters(self, server) -> None:
        server.audit_logger.log(action="a", identity="alice")
        server.audit_logger.log(action="b", identity="bob")

        status, data = _get_json(server.port, "/api/audit?identity=alice")
        assert status == 200
        assert len(data["events"]) == 1
        assert data["events"][0]["identity"] == "alice"

    def test_audit_query_limit(self, server) -> None:
        for i in range(10):
            server.audit_logger.log(action=f"action_{i}")

        status, data = _get_json(server.port, "/api/audit?limit=3")
        assert status == 200
        assert len(data["events"]) == 3

    def test_audit_export_json(self, server) -> None:
        server.audit_logger.log(action="test", identity="user")

        conn = HTTPConnection("127.0.0.1", server.port)
        conn.request("GET", "/api/audit/export?format=json", headers={"Accept": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        assert resp.status == 200
        parsed = json.loads(data)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_audit_export_csv(self, server) -> None:
        server.audit_logger.log(action="test", identity="user")

        conn = HTTPConnection("127.0.0.1", server.port)
        conn.request("GET", "/api/audit/export?format=csv", headers={"Accept": "application/json"})
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        conn.close()
        assert resp.status == 200
        assert "action" in data
        assert "identity" in data


# ── POST handlers return JSON ────────────────────────────────────────────


class TestPOSTJsonResponses:
    def test_worker_start_json(self, server) -> None:
        status, data = _post_json(server.port, "/worker-start")
        # May return 200 or 409 depending on worker state
        assert status in (200, 409)

    def test_worker_stop_json(self, server) -> None:
        status, data = _post_json(server.port, "/worker-stop")
        # May return 200 or 500 depending on worker state
        assert status in (200, 500, 504)

    def test_bulk_retry_json(self, server) -> None:
        status, data = _post_json(server.port, "/bulk-retry-failed")
        assert status == 200
        assert data.get("ok") is True

    def test_bulk_clear_json(self, server) -> None:
        status, data = _post_json(server.port, "/bulk-clear-dead")
        assert status == 200
        assert data.get("ok") is True

    def test_workflow_save_json(self, server) -> None:
        body = "name=test_wf&yaml=name: test_wf\nsteps: []"
        status, data = _post_json(server.port, "/workflow/save", body)
        # May succeed or fail depending on validation
        assert status in (200, 400)

    def test_workflow_delete_missing_name(self, server) -> None:
        status, data = _post_json(server.port, "/workflow/delete", "name=")
        assert status == 400

    def test_trigger_save_json(self, server) -> None:
        body = "name=test_trigger&yaml=name: test_trigger\ntype: cron\nworkflow: test"
        status, data = _post_json(server.port, "/trigger/save", body)
        assert status in (200, 400)

    def test_config_save_json(self, server) -> None:
        body = "toml=[paths]\ncache_dir = '/tmp/test'"
        status, data = _post_json(server.port, "/config/save", body)
        assert status in (200, 400)

    def test_delete_missing_sid(self, server) -> None:
        status, data = _post_json(server.port, "/delete", "sid=")
        assert status == 400

    def test_rerun_missing_sid(self, server) -> None:
        status, data = _post_json(server.port, "/rerun", "sid=")
        assert status == 400


# ── RBAC enforcement (synthetic admin = all allowed) ─────────────────────


class TestRBACNoAuth:
    """When OIDC is disabled, synthetic admin claims are used — everything allowed."""

    def test_all_get_endpoints_accessible(self, server) -> None:
        endpoints = [
            "/",
            "/workflows",
            "/triggers",
            "/history",
            "/config",
            "/modules",
            "/examples",
            "/worker-status",
            "/api/audit",
        ]
        for ep in endpoints:
            status, _ = _get_json(server.port, ep)
            assert status == 200, f"GET {ep} returned {status}"

    def test_all_post_endpoints_accessible(self, server) -> None:
        """POST endpoints should not return 403 (though they may return other errors)."""
        endpoints = [
            ("/worker-start", ""),
            ("/bulk-retry-failed", ""),
            ("/bulk-clear-dead", ""),
        ]
        for ep, body in endpoints:
            status, _ = _post_json(server.port, ep, body)
            assert status != 403, f"POST {ep} returned 403"


# ── Audit events recorded ───────────────────────────────────────────────


class TestAuditRecording:
    def test_post_action_creates_audit_event(self, server) -> None:
        initial_count = server.audit_logger.count()
        _post_json(server.port, "/bulk-retry-failed")
        final_count = server.audit_logger.count()
        assert final_count > initial_count

    def test_audit_event_has_correct_action(self, server) -> None:
        _post_json(server.port, "/bulk-clear-dead")
        events = server.audit_logger.query(limit=1)
        assert len(events) >= 1
        # Most recent event should be the bulk clear
        assert "bulk" in events[0]["action"] or "clear" in events[0]["action"]


# ── Audit verify endpoint ──────────────────────────────────────────────


class TestAuditVerify:
    def test_audit_verify_returns_valid(self, server) -> None:
        """GET /api/audit/verify should return chain verification results."""
        status, data = _get_json(server.port, "/api/audit/verify")
        assert status == 200
        assert "valid" in data
        assert data["valid"] is True
        assert "total" in data
        assert "verified" in data

    def test_audit_verify_with_events(self, server) -> None:
        """Verify endpoint works after logging events."""
        server.audit_logger.log(action="test1", identity="alice")
        server.audit_logger.log(action="test2", identity="bob")

        status, data = _get_json(server.port, "/api/audit/verify")
        assert status == 200
        assert data["valid"] is True

    def test_audit_verify_hmac_not_enabled_message(self, server) -> None:
        """Without HMAC key, verify should indicate signing is not enabled."""
        status, data = _get_json(server.port, "/api/audit/verify")
        assert status == 200
        # Server fixture creates AuditLogger without hmac_key,
        # so it should report not enabled or return 0 verified
        assert data["valid"] is True
        assert data["verified"] == 0
