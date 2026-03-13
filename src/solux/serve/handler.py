from __future__ import annotations

import json
import logging
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..config import default_workflow_name, effective_external_modules_dir
from .api import (
    get_index_data,
    handle_bulk_clear_dead_letter,
    handle_bulk_retry_failed,
    handle_delete,
    handle_delete_trigger,
    handle_delete_workflow,
    handle_get_config,
    handle_get_trigger_yaml,
    handle_ingest_file,
    handle_ingest_url,
    handle_list_triggers,
    handle_list_workflows,
    handle_rerun,
    handle_worker_restart,
    handle_save_config,
    handle_set_trigger_enabled,
    handle_save_trigger,
    handle_save_workflow,
    handle_run_trigger_now,
    handle_trigger_webhook,
    trigger_last_seen_by_name,
    handle_worker_start,
    handle_worker_stop,
    handle_worker_status,
    verify_webhook_signature,
)
from .http_utils import (
    MAX_API_BODY_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_WEBHOOK_BYTES,
    is_safe_workflow_name,
    parse_multipart_form,
)
from .rate_limit import WebhookRateLimiter
from .rbac import check_permission, extract_roles, highest_role
from .sources import safe_select_source, safe_select_file, discover_sources, _result_files
from .templates import (
    build_config_editor_page,
    build_examples_page,
    build_history_page,
    build_modules_page,
    build_page,
    build_trigger_editor_page,
    build_triggers_page,
    build_workflow_editor_page,
    build_workflows_page,
    render_file_content,
)

_log = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = MAX_UPLOAD_BYTES
_MAX_WEBHOOK_BYTES = MAX_WEBHOOK_BYTES
_MAX_API_BODY_BYTES = MAX_API_BODY_BYTES
_WebhookRateLimiter = WebhookRateLimiter
_is_safe_workflow_name = is_safe_workflow_name
_parse_multipart = parse_multipart_form

# Synthetic claims returned when OIDC is disabled (local/dev mode)
_SYNTHETIC_ADMIN_CLAIMS: dict[str, Any] = {
    "sub": "local-admin",
    "preferred_username": "admin",
    "realm_access": {"roles": ["admin"]},
}


def _triggers_dir(config) -> Path | None:
    """Return the triggers directory from config, or None if config unavailable."""
    if config is None:
        return None
    td = getattr(config, "triggers_dir", None)
    return td if td is not None else None


def _config_path(config) -> Path:
    """Return the config file path from config, falling back to the default."""
    from ..config import get_default_config_path

    if config is not None:
        cp = getattr(config, "config_path", None)
        if cp is not None:
            return Path(cp)
    return get_default_config_path()


def build_handler(
    cache_dir: Path,
    *,
    yt_dlp_binary: str | None,
    config=None,
    workflows_dir: Path | None = None,
    audit_logger=None,
) -> type[BaseHTTPRequestHandler]:
    _rate_limit = 60
    _default_workflow = default_workflow_name(config)
    if config is not None:
        sec = getattr(config, "security", None)
        if sec is not None:
            _rate_limit = int(getattr(sec, "webhook_rate_limit", 60))
    _webhook_rl = _WebhookRateLimiter(max_per_minute=_rate_limit)

    # Resolve OIDC role claim path from config
    _role_claim = "realm_access.roles"
    if config is not None:
        sec = getattr(config, "security", None)
        if sec is not None:
            _role_claim = getattr(sec, "oidc_role_claim", _role_claim) or _role_claim

    class Handler(BaseHTTPRequestHandler):
        def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_text(self, text: str, content_type: str = "text/plain; charset=utf-8", status: int = 200) -> None:
            self._send_bytes(text.encode("utf-8"), content_type, status=status)

        def _send_json(self, data: dict | list, status: int = 200) -> None:
            self._send_text(
                json.dumps(data, default=str), content_type="application/json; charset=utf-8", status=status
            )

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _wants_json(self) -> bool:
            """Check if the client prefers JSON (Accept: application/json)."""
            accept = self.headers.get("Accept", "")
            return "application/json" in accept

        def _check_auth(self) -> dict[str, Any] | None:
            """Validate auth and return JWT claims dict, or None on failure.

            When OIDC is not required, returns synthetic admin claims.
            On auth failure, sends the appropriate error response and returns None.
            """
            if config is None:
                return dict(_SYNTHETIC_ADMIN_CLAIMS)
            sec = getattr(config, "security", None)
            if sec is None or not getattr(sec, "oidc_require_auth", False):
                return dict(_SYNTHETIC_ADMIN_CLAIMS)
            issuer = getattr(sec, "oidc_issuer", "")
            audience = getattr(sec, "oidc_audience", "")
            if not issuer or not audience:
                if self._wants_json():
                    self._send_json({"error": "OIDC not configured"}, status=500)
                else:
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                return None
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                if self._wants_json():
                    self._send_json({"error": "missing bearer token"}, status=401)
                else:
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", "Bearer")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                return None
            token = auth_header[7:]
            from .auth import get_validator

            allowed_algs = tuple(getattr(sec, "oidc_allowed_algs", ()) or ())
            validator = get_validator(
                issuer,
                audience,
                allowed_algorithms=allowed_algs or None,
            )
            claims = validator.validate(token)
            if claims is None:
                if self._wants_json():
                    self._send_json({"error": "invalid token"}, status=401)
                else:
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Bearer error="invalid_token"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                return None
            return claims

        def _get_roles(self, claims: dict[str, Any]) -> list[str]:
            """Extract roles from validated claims."""
            return extract_roles(claims, _role_claim)

        def _check_permission(self, claims: dict[str, Any], permission: str) -> bool:
            """Check if the authenticated user has the required permission.

            Sends 403 and returns False if denied.
            """
            roles = self._get_roles(claims)
            if check_permission(roles, permission):
                return True
            if self._wants_json():
                self._send_json(
                    {"error": "forbidden", "required_permission": permission, "roles": roles},
                    status=403,
                )
            else:
                self._send_text(f"Forbidden: requires {permission}", status=403)
            return False

        def _identity(self, claims: dict[str, Any]) -> str:
            """Extract user identity from claims."""
            return str(claims.get("preferred_username") or claims.get("sub") or "unknown")

        def _client_ip(self) -> str:
            """Get client IP address, respecting X-Forwarded-For."""
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return self.client_address[0] if self.client_address else ""

        def _audit(
            self,
            claims: dict[str, Any],
            action: str,
            resource: str = "",
            result: str = "success",
            detail: dict[str, Any] | None = None,
        ) -> None:
            """Emit an audit event if audit logging is available."""
            if audit_logger is None:
                return
            try:
                audit_logger.log(
                    identity=self._identity(claims),
                    ip_address=self._client_ip(),
                    action=action,
                    resource=resource,
                    result=result,
                    detail=detail,
                )
            except Exception as exc:
                _log.warning("Failed to write audit event: %s", exc)

        def _origin_matches_host(self, value: str) -> bool:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"}:
                return False
            host_header = (self.headers.get("Host") or "").strip().lower()
            if not host_header:
                return False
            return parsed.netloc.strip().lower() == host_header

        def _csrf_allowed(self, path: str) -> bool:
            # Webhook endpoints are machine-to-machine and do not rely on browser cookies.
            if path.startswith("/api/trigger/"):
                return True
            # JSON API calls from Next.js UI use Bearer tokens, not cookies.
            if self._wants_json():
                return True

            sec_fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
            if sec_fetch_site == "cross-site":
                return False

            origin = (self.headers.get("Origin") or "").strip()
            if origin:
                return self._origin_matches_host(origin)

            referer = (self.headers.get("Referer") or "").strip()
            if referer:
                return self._origin_matches_host(referer)

            # Some non-browser clients do not send Origin/Referer.
            return True

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._handle_healthz()
                return
            if parsed.path == "/events":
                claims = self._check_auth()
                if claims is None:
                    return
                self._handle_sse()
                return
            claims = self._check_auth()
            if claims is None:
                return
            if parsed.path == "/":
                self._handle_index(parse_qs(parsed.query), claims)
                return
            if parsed.path == "/raw":
                self._handle_raw(parse_qs(parsed.query))
                return
            if parsed.path == "/worker-status":
                self._handle_worker_status()
                return
            if parsed.path == "/workflows":
                self._handle_workflows_list(claims)
                return
            if parsed.path.startswith("/workflow/") and parsed.path not in ("/workflow/save", "/workflow/delete"):
                wf_name = parsed.path[len("/workflow/") :]
                if not _is_safe_workflow_name(wf_name):
                    self._send_text("Invalid workflow name", status=400)
                    return
                self._handle_workflow_editor(wf_name, parse_qs(parsed.query), claims)
                return
            if parsed.path == "/triggers":
                self._handle_triggers_list(claims)
                return
            if parsed.path.startswith("/trigger/") and parsed.path not in ("/trigger/save", "/trigger/delete"):
                tr_name = parsed.path[len("/trigger/") :]
                if not _is_safe_workflow_name(tr_name):
                    self._send_text("Invalid trigger name", status=400)
                    return
                self._handle_trigger_editor(tr_name, parse_qs(parsed.query), claims)
                return
            if parsed.path == "/config":
                self._handle_config_editor(claims, saved=False)
                return
            if parsed.path == "/examples":
                self._handle_examples(claims)
                return
            if parsed.path == "/modules":
                self._handle_modules_catalog(claims)
                return
            if parsed.path == "/history":
                self._handle_history(parse_qs(parsed.query), claims)
                return
            if parsed.path == "/api/audit":
                self._handle_audit_query(parse_qs(parsed.query), claims)
                return
            if parsed.path == "/api/audit/export":
                self._handle_audit_export(parse_qs(parsed.query), claims)
                return
            if parsed.path == "/api/audit/verify":
                self._handle_audit_verify(claims)
                return
            if parsed.path.startswith("/api/job/"):
                self._handle_job_detail(parsed.path, claims)
                return
            self._send_text("Not found", status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)

            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (ValueError, TypeError):
                content_length = 0

            # Apply per-route size limits.
            if parsed.path.startswith("/api/trigger/"):
                max_bytes = _MAX_WEBHOOK_BYTES
            elif parsed.path == "/ingest-file":
                max_bytes = _MAX_UPLOAD_BYTES
            else:
                max_bytes = _MAX_API_BODY_BYTES

            if content_length > max_bytes:
                self._send_text(
                    f"Payload too large (max {max_bytes // 1024} KiB for this endpoint)",
                    status=413,
                )
                return

            claims = self._check_auth()
            if claims is None:
                return
            if not self._csrf_allowed(parsed.path):
                self._send_text("Forbidden by CSRF policy", status=403)
                return

            try:
                raw_body = self.rfile.read(content_length)
            except OSError:
                raw_body = b""

            if parsed.path.startswith("/api/trigger/"):
                wf_name = parsed.path[len("/api/trigger/") :]
                if not _is_safe_workflow_name(wf_name):
                    self._send_json({"error": "Invalid workflow name"}, status=400)
                    return
                if not _webhook_rl.allow(self.client_address[0]):
                    self._send_json({"error": "Rate limit exceeded"}, status=429)
                    return
                self._handle_trigger_webhook(wf_name, raw_body, claims)
                return

            if parsed.path == "/worker-start":
                if not self._check_permission(claims, "worker.start"):
                    return
                self._handle_worker_start(claims)
            elif parsed.path == "/worker-stop":
                if not self._check_permission(claims, "worker.stop"):
                    return
                self._handle_worker_stop(claims)
            elif parsed.path == "/worker-restart":
                if not self._check_permission(claims, "worker.restart"):
                    return
                form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
                self._handle_worker_restart(form_data, claims)
            elif parsed.path == "/ingest-url":
                if not self._check_permission(claims, "sources.ingest"):
                    return
                form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
                self._handle_ingest_url(form_data, claims)
            elif parsed.path == "/ingest-file":
                if not self._check_permission(claims, "sources.ingest"):
                    return
                self._handle_ingest_file(raw_body, claims)
            elif parsed.path in ("/delete", "/rerun"):
                perm = "jobs.delete" if parsed.path == "/delete" else "jobs.retry"
                if not self._check_permission(claims, perm):
                    return
                form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
                if parsed.path == "/delete":
                    self._handle_delete(form_data, claims)
                else:
                    self._handle_rerun(form_data, claims)
            elif parsed.path == "/workflow/save":
                if not self._check_permission(claims, "workflows.create"):
                    return
                self._handle_workflow_save(raw_body, claims)
            elif parsed.path == "/workflow/delete":
                if not self._check_permission(claims, "workflows.delete"):
                    return
                self._handle_workflow_delete(raw_body, claims)
            elif parsed.path == "/trigger/save":
                if not self._check_permission(claims, "triggers.create"):
                    return
                self._handle_trigger_save(raw_body, claims)
            elif parsed.path == "/trigger/delete":
                if not self._check_permission(claims, "triggers.delete"):
                    return
                self._handle_trigger_delete(raw_body, claims)
            elif parsed.path == "/trigger/toggle":
                if not self._check_permission(claims, "triggers.toggle"):
                    return
                self._handle_trigger_toggle(raw_body, claims)
            elif parsed.path == "/trigger/run-now":
                if not self._check_permission(claims, "triggers.run"):
                    return
                self._handle_trigger_run_now(raw_body, claims)
            elif parsed.path == "/workflow/run-now":
                if not self._check_permission(claims, "workflows.run"):
                    return
                self._handle_workflow_run_now(raw_body, claims)
            elif parsed.path == "/config/save":
                if not self._check_permission(claims, "config.save"):
                    return
                self._handle_config_save(raw_body, claims)
            elif parsed.path == "/bulk-retry-failed":
                if not self._check_permission(claims, "jobs.retry"):
                    return
                self._handle_bulk_retry_failed(claims)
            elif parsed.path == "/bulk-clear-dead":
                if not self._check_permission(claims, "jobs.clear"):
                    return
                self._handle_bulk_clear_dead(claims)
            else:
                self._send_text("Not found", status=404)

        # ── GET /api/job/{job_id} ───────────────────────────────────────

        def _handle_job_detail(self, path: str, claims: dict[str, Any]) -> None:
            if not self._check_permission(claims, "jobs.list"):
                return
            job_id = path[len("/api/job/") :]
            if not job_id or not re.match(r"^[a-zA-Z0-9_-]+$", job_id):
                self._send_json({"error": "Invalid job ID"}, status=400)
                return
            from ..queueing import read_job

            job = read_job(cache_dir, job_id)
            if job is None:
                self._send_json({"error": "Job not found"}, status=404)
                return
            # Attach context.json if source_id exists
            sid = job.get("source_id")
            if sid:
                from ..paths import source_dir as _sd

                sdir = _sd(cache_dir, sid)
                ctx_path = sdir / "context.json"
                if ctx_path.exists():
                    try:
                        job["context"] = json.loads(ctx_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        pass
                # Attach result file list
                try:
                    files = _result_files(sdir)
                    job["result_files"] = [{"name": f.name, "size_bytes": f.size_bytes} for f in files]
                except OSError:
                    pass
            self._send_json(job)

        # ── POST handlers ────────────────────────────────────────────────

        def _handle_delete(self, form_data: dict, claims: dict[str, Any]) -> None:
            sid_list = form_data.get("sid", [])
            if not sid_list or not sid_list[0]:
                self._send_text("Missing sid", status=400)
                return
            ok, err = handle_delete(cache_dir, sid_list[0])
            self._audit(claims, "jobs.delete", sid_list[0], "success" if ok else "failure")
            if not ok:
                self._send_text(err, status=400)
                return
            if self._wants_json():
                self._send_json({"ok": True})
            else:
                self._redirect("/")

        def _handle_rerun(self, form_data: dict, claims: dict[str, Any]) -> None:
            sid_list = form_data.get("sid", [])
            if not sid_list or not sid_list[0]:
                self._send_text("Missing sid", status=400)
                return
            mode = (form_data.get("mode") or ["full"])[0]
            output_format = (form_data.get("format") or ["markdown"])[0]
            ok, result = handle_rerun(
                cache_dir,
                sid_list[0],
                mode,
                output_format,
                default_workflow=_default_workflow,
            )
            self._audit(claims, "jobs.retry", sid_list[0], "success" if ok else "failure")
            if not ok:
                self._send_text(result, status=400 if "Invalid" in result or "not found" in result.lower() else 500)
                return
            if self._wants_json():
                self._send_json({"ok": True, "job_id": sid_list[0]})
            else:
                self._redirect(f"/?sid={sid_list[0]}")

        def _handle_ingest_url(self, form_data: dict, claims: dict[str, Any]) -> None:
            url = (form_data.get("url") or [""])[0].strip()
            if not url:
                self._send_text("Missing url", status=400)
                return
            mode = (form_data.get("mode") or ["full"])[0]
            output_format = (form_data.get("format") or ["markdown"])[0]
            workflow_name = (form_data.get("workflow") or [_default_workflow])[0] or _default_workflow
            handle_ingest_url(cache_dir, url, mode, output_format, workflow_name)
            self._audit(claims, "sources.ingest", url)
            if self._wants_json():
                self._send_json({"ok": True, "url": url, "workflow": workflow_name})
            else:
                self._redirect("/")

        def _handle_ingest_file(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            content_type = self.headers.get("Content-Type", "")
            boundary_match = re.search(r"boundary=(.+)", content_type)
            if not boundary_match:
                self._send_text("Missing multipart boundary", status=400)
                return
            boundary = boundary_match.group(1).strip().encode("utf-8")
            parts = _parse_multipart(raw_body, boundary)

            file_data: bytes | None = None
            file_name: str | None = None
            fields: dict[str, str] = {}
            for part in parts:
                if part.get("filename"):
                    file_data = part["data"]
                    file_name = part["filename"]
                elif part.get("name"):
                    fields[part["name"]] = part["data"].decode("utf-8", errors="replace")

            if not file_data or not file_name:
                self._send_text("No file uploaded", status=400)
                return

            mode = fields.get("mode", "full")
            output_format = fields.get("format", "markdown")
            workflow_name = fields.get("workflow", _default_workflow) or _default_workflow
            ok, job_id = handle_ingest_file(cache_dir, file_data, file_name, mode, output_format, workflow_name)
            self._audit(claims, "sources.ingest", file_name)
            if self._wants_json():
                self._send_json({"ok": True, "filename": file_name, "workflow": workflow_name, "job_id": job_id})
            else:
                self._redirect("/")

        def _handle_worker_start(self, claims: dict[str, Any]) -> None:
            ok, err = handle_worker_start(cache_dir)
            self._audit(claims, "worker.start", result="success" if ok else "failure")
            if ok:
                if self._wants_json():
                    self._send_json({"ok": True})
                else:
                    self._redirect("/")
                return
            self._send_text(err, status=409)

        def _handle_worker_stop(self, claims: dict[str, Any]) -> None:
            ok, reason = handle_worker_stop(cache_dir)
            self._audit(claims, "worker.stop", result="success" if ok else "failure")
            if ok:
                if self._wants_json():
                    self._send_json({"ok": True})
                else:
                    self._redirect("/")
                return
            if reason == "timeout":
                self._send_text("Worker did not stop within timeout", status=504)
                return
            self._send_text(f"Could not stop worker: {reason}", status=500)

        def _handle_worker_restart(self, form_data: dict, claims: dict[str, Any]) -> None:
            next_path = (form_data.get("next") or ["/triggers"])[0]
            if not isinstance(next_path, str) or not next_path.startswith("/") or next_path.startswith("//"):
                next_path = "/triggers"
            ok, reason = handle_worker_restart(cache_dir)
            self._audit(claims, "worker.restart", result="success" if ok else "failure")
            if ok:
                if self._wants_json():
                    self._send_json({"ok": True})
                else:
                    self._redirect(next_path)
                return
            if reason == "timeout":
                self._send_text("Worker did not stop within timeout", status=504)
                return
            self._send_text(f"Could not restart worker: {reason}", status=500)

        def _handle_worker_status(self) -> None:
            info = handle_worker_status(cache_dir)
            payload = json.dumps(info, default=str)
            self._send_text(payload, content_type="application/json; charset=utf-8")

        def _handle_trigger_webhook(self, workflow_name: str, raw_body: bytes, claims: dict[str, Any]) -> None:
            # Verify HMAC signature when webhook_secret is configured.
            webhook_secret = ""
            if config is not None:
                sec = getattr(config, "security", None)
                if sec is not None:
                    webhook_secret = getattr(sec, "webhook_secret", "") or ""
            if webhook_secret:
                sig_header = self.headers.get("X-Solux-Signature", "")
                if not sig_header:
                    self._send_json({"error": "Missing X-Solux-Signature header"}, status=401)
                    return
                if not verify_webhook_signature(raw_body, sig_header, webhook_secret):
                    self._send_json({"error": "Invalid webhook signature"}, status=403)
                    return

            try:
                params = json.loads(raw_body) if raw_body else {}
                if not isinstance(params, dict):
                    params = {}
            except json.JSONDecodeError:
                _log.warning("Webhook %r received non-JSON body; treating as empty params", workflow_name)
                params = {}
            ok, result = handle_trigger_webhook(
                cache_dir,
                workflow_name,
                params,
                workflows_dir=workflows_dir,
                config=config,
            )
            self._audit(claims, "triggers.webhook", workflow_name, "success" if ok else "failure")
            if ok:
                if isinstance(result, dict):
                    self._send_json(result)
                else:
                    self._send_json({"status": str(result)})
            else:
                self._send_json({"error": str(result)}, status=400)

        def _handle_workflow_save(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            name = (form_data.get("name") or [""])[0].strip()
            yaml_content = (form_data.get("yaml") or [""])[0]
            wf_dir = workflows_dir or cache_dir / "workflows.d"
            ok, err = handle_save_workflow(cache_dir, wf_dir, name, yaml_content)
            self._audit(claims, "workflows.save", name, "success" if ok else "failure")
            if self._wants_json():
                if ok:
                    self._send_json({"ok": True, "name": name})
                else:
                    self._send_json({"error": err}, status=400)
                return
            if ok:
                page = build_workflow_editor_page(name, yaml_content, [], saved=True)
                self._send_text(page, content_type="text/html; charset=utf-8")
            else:
                page = build_workflow_editor_page(name, yaml_content, [err])
                self._send_text(page, content_type="text/html; charset=utf-8", status=400)

        def _handle_workflow_delete(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            name = (form_data.get("name") or [""])[0].strip()
            if not name or not _is_safe_workflow_name(name):
                self._send_text("Invalid workflow name", status=400)
                return
            wf_dir = workflows_dir or cache_dir / "workflows.d"
            ok, err = handle_delete_workflow(wf_dir, name)
            self._audit(claims, "workflows.delete", name, "success" if ok else "failure")
            if self._wants_json():
                if ok:
                    self._send_json({"ok": True})
                else:
                    self._send_json({"error": err}, status=400)
                return
            if ok:
                self._redirect("/workflows")
            else:
                self._send_text(err, status=400)

        def _handle_trigger_save(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            name = (form_data.get("name") or [""])[0].strip()
            yaml_content = (form_data.get("yaml") or [""])[0]
            tr_dir = _triggers_dir(config) or cache_dir / "triggers.d"
            ok, err = handle_save_trigger(tr_dir, name, yaml_content)
            self._audit(claims, "triggers.save", name, "success" if ok else "failure")
            if self._wants_json():
                if ok:
                    self._send_json({"ok": True, "name": name})
                else:
                    self._send_json({"error": err}, status=400)
                return
            if ok:
                page = build_trigger_editor_page(name, yaml_content, [], saved=True)
                self._send_text(page, content_type="text/html; charset=utf-8")
            else:
                page = build_trigger_editor_page(name, yaml_content, [err])
                self._send_text(page, content_type="text/html; charset=utf-8", status=400)

        def _handle_trigger_delete(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            name = (form_data.get("name") or [""])[0].strip()
            if not name or not _is_safe_workflow_name(name):
                self._send_text("Invalid trigger name", status=400)
                return
            tr_dir = _triggers_dir(config) or cache_dir / "triggers.d"
            ok, err = handle_delete_trigger(tr_dir, name)
            self._audit(claims, "triggers.delete", name, "success" if ok else "failure")
            if self._wants_json():
                if ok:
                    self._send_json({"ok": True})
                else:
                    self._send_json({"error": err}, status=400)
                return
            if ok:
                self._redirect("/triggers")
            else:
                self._send_text(err, status=400)

        def _handle_trigger_toggle(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            name = (form_data.get("name") or [""])[0].strip()
            enabled_raw = (form_data.get("enabled") or [""])[0].strip().lower()
            next_path = (form_data.get("next") or ["/"])[0]
            if not isinstance(next_path, str) or not next_path.startswith("/") or next_path.startswith("//"):
                next_path = "/"
            if not name or not _is_safe_workflow_name(name):
                self._send_text("Invalid trigger name", status=400)
                return
            enabled = enabled_raw in {"1", "true", "yes", "on"}
            tr_dir = _triggers_dir(config) or cache_dir / "triggers.d"
            ok, err = handle_set_trigger_enabled(tr_dir, name, enabled)
            self._audit(claims, "triggers.toggle", name, "success" if ok else "failure", {"enabled": enabled})
            if not ok:
                self._send_text(err, status=400)
                return
            if self._wants_json():
                self._send_json({"ok": True, "enabled": enabled})
            else:
                self._redirect(next_path)

        def _handle_trigger_run_now(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            name = (form_data.get("name") or [""])[0].strip()
            next_path = (form_data.get("next") or ["/"])[0]
            if not isinstance(next_path, str) or not next_path.startswith("/") or next_path.startswith("//"):
                next_path = "/"
            if not name or not _is_safe_workflow_name(name):
                self._send_text("Invalid trigger name", status=400)
                return
            tr_dir = _triggers_dir(config) or cache_dir / "triggers.d"
            ok, err = handle_run_trigger_now(cache_dir, tr_dir, name)
            self._audit(claims, "triggers.run", name, "success" if ok else "failure")
            if not ok:
                self._send_text(err, status=400)
                return
            if self._wants_json():
                self._send_json({"ok": True})
            else:
                self._redirect(next_path)

        def _handle_workflow_run_now(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            name = (form_data.get("name") or [""])[0].strip()
            next_path = (form_data.get("next") or ["/"])[0]
            if not isinstance(next_path, str) or not next_path.startswith("/") or next_path.startswith("//"):
                next_path = "/"
            if not name or not _is_safe_workflow_name(name):
                self._send_text("Invalid workflow name", status=400)
                return
            ok, result = handle_trigger_webhook(
                cache_dir,
                name,
                {"source": f"manual://workflow/{name}", "_trigger_manual": True},
                workflows_dir=workflows_dir,
                config=config,
            )
            self._audit(claims, "workflows.run", name, "success" if ok else "failure")
            if not ok:
                if self._wants_json():
                    self._send_json({"error": str(result)}, status=400)
                else:
                    self._send_text(str(result), status=400)
                return
            if self._wants_json():
                if isinstance(result, dict):
                    self._send_json({"ok": True, **result})
                else:
                    self._send_json({"ok": True, "status": str(result)})
            else:
                self._redirect(next_path)

        def _handle_config_save(self, raw_body: bytes, claims: dict[str, Any]) -> None:
            form_data = parse_qs(raw_body.decode("utf-8", errors="replace"))
            toml_content = (form_data.get("toml") or [""])[0]
            cfg_path = _config_path(config)
            ok, err = handle_save_config(cfg_path, toml_content)
            self._audit(claims, "config.save", str(cfg_path), "success" if ok else "failure")
            if self._wants_json():
                if ok:
                    self._send_json({"ok": True})
                else:
                    self._send_json({"error": err}, status=400)
                return
            if ok:
                page = build_config_editor_page(str(cfg_path), toml_content, saved=True)
                self._send_text(page, content_type="text/html; charset=utf-8")
            else:
                page = build_config_editor_page(str(cfg_path), toml_content, error=err)
                self._send_text(page, content_type="text/html; charset=utf-8", status=400)

        def _handle_bulk_retry_failed(self, claims: dict[str, Any]) -> None:
            handle_bulk_retry_failed(cache_dir)
            self._audit(claims, "jobs.bulk_retry")
            if self._wants_json():
                self._send_json({"ok": True})
            else:
                self._redirect("/history")

        def _handle_bulk_clear_dead(self, claims: dict[str, Any]) -> None:
            handle_bulk_clear_dead_letter(cache_dir)
            self._audit(claims, "jobs.bulk_clear")
            if self._wants_json():
                self._send_json({"ok": True})
            else:
                self._redirect("/history")

        # ── GET handlers (with JSON branches) ────────────────────────────

        def _handle_workflows_list(self, claims: dict[str, Any]) -> None:
            wf_dir = workflows_dir
            workflows, errors = handle_list_workflows(wf_dir)
            if self._wants_json():
                data = [
                    {
                        "name": str(getattr(wf, "name", "")),
                        "description": str(getattr(wf, "description", "")),
                        "steps": len(getattr(wf, "steps", [])),
                    }
                    for wf in workflows
                ]
                self._send_json({"workflows": data, "errors": errors})
                return
            page = build_workflows_page(workflows, errors)
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_workflow_editor(self, name: str, query: dict, claims: dict[str, Any]) -> None:
            if not _is_safe_workflow_name(name):
                self._send_text("Invalid workflow name", status=400)
                return
            wf_dir = workflows_dir
            yaml_content = ""
            validation_issues: list[str] = []
            if wf_dir and name and name != "new":
                for ext in (".yaml", ".yml"):
                    p = wf_dir / f"{name}{ext}"
                    if p.exists():
                        yaml_content = p.read_text(encoding="utf-8")
                        break
            # If no file found (for example a built-in workflow), synthesize YAML.
            if not yaml_content and name and name != "new":
                try:
                    import yaml

                    from ..workflows.loader import load_workflow, workflow_to_dict

                    wf_obj = load_workflow(name, workflow_dir=wf_dir)
                    yaml_content = yaml.safe_dump(workflow_to_dict(wf_obj), sort_keys=False, allow_unicode=True)
                except Exception:
                    yaml_content = ""
            # If no file found (new workflow or not in dir), check for ?template=
            if not yaml_content:
                template_name = (query.get("template") or [None])[0]
                if template_name:
                    from ..workflows.examples import get_workflow_example

                    ex = get_workflow_example(template_name)
                    if ex:
                        yaml_content = ex["yaml"]

            if self._wants_json():
                parsed_steps: list[dict[str, Any]] = []
                if yaml_content and name != "new":
                    try:
                        from ..workflows.loader import load_workflow, workflow_to_dict

                        wf_obj = load_workflow(name, workflow_dir=wf_dir)
                        parsed_steps = workflow_to_dict(wf_obj)["steps"]
                    except Exception:
                        pass
                meta: dict[str, Any] = {}
                if yaml_content:
                    try:
                        import yaml as _yaml

                        raw = _yaml.safe_load(yaml_content)
                        if isinstance(raw, dict) and "meta" in raw:
                            meta = raw["meta"]
                    except Exception:
                        pass
                self._send_json({"name": name, "yaml": yaml_content, "steps": parsed_steps, "meta": meta})
                return
            page = build_workflow_editor_page(name, yaml_content, validation_issues)
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_triggers_list(self, claims: dict[str, Any]) -> None:
            tr_dir = _triggers_dir(config)
            triggers, errors = handle_list_triggers(tr_dir)
            if self._wants_json():
                data = [
                    {
                        "name": str(getattr(tr, "name", "")),
                        "type": str(getattr(tr, "type", "")),
                        "workflow": str(getattr(tr, "workflow", "")),
                        "enabled": bool(getattr(tr, "enabled", True)),
                    }
                    for tr in triggers
                ]
                self._send_json({"triggers": data, "errors": errors})
                return
            page = build_triggers_page(triggers, errors)
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_trigger_editor(self, name: str, query: dict, claims: dict[str, Any]) -> None:
            tr_dir = _triggers_dir(config)
            yaml_content = ""
            if name != "new":
                yaml_content = handle_get_trigger_yaml(tr_dir, name) if tr_dir else ""
            if not yaml_content:
                template_name = (query.get("template") or [None])[0]
                if template_name:
                    from ..workflows.examples import get_trigger_example

                    ex = get_trigger_example(template_name)
                    if ex:
                        yaml_content = ex["yaml"]
                elif name in ("new", ""):
                    yaml_content = (
                        "name: my_trigger\n"
                        "enabled: false\n"
                        "type: folder_watch\n"
                        f"workflow: {_default_workflow}\n"
                        "params: {}\n"
                        "config:\n"
                        "  path: ~/Downloads\n"
                        '  pattern: "*.mp3"\n'
                        "  interval: 30\n"
                    )
            if self._wants_json():
                self._send_json({"name": name, "yaml": yaml_content})
                return
            page = build_trigger_editor_page(name, yaml_content, [])
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_config_editor(self, claims: dict[str, Any], *, saved: bool = False, error: str = "") -> None:
            cfg_path = _config_path(config)
            toml_content = handle_get_config(cfg_path)
            if self._wants_json():
                self._send_json({"path": str(cfg_path), "content": toml_content})
                return
            page = build_config_editor_page(str(cfg_path), toml_content, saved=saved, error=error)
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_examples(self, claims: dict[str, Any]) -> None:
            from ..workflows.examples import WORKFLOW_EXAMPLES, TRIGGER_EXAMPLES

            if self._wants_json():
                self._send_json({"workflows": WORKFLOW_EXAMPLES, "triggers": TRIGGER_EXAMPLES})
                return
            page = build_examples_page(WORKFLOW_EXAMPLES, TRIGGER_EXAMPLES)
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_modules_catalog(self, claims: dict[str, Any]) -> None:
            from ..modules.discovery import discover_modules

            external_dir = effective_external_modules_dir(config)
            if not isinstance(external_dir, Path):
                external_dir = None
            specs = list(discover_modules(external_dir=external_dir))
            if self._wants_json():
                data = [
                    {
                        "type": str(getattr(s, "type_name", "")),
                        "category": str(getattr(s, "category", "")),
                        "description": str(getattr(s, "description", "")),
                    }
                    for s in specs
                ]
                self._send_json({"modules": data})
                return
            page = build_modules_page(specs)
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_history(self, query: dict | None = None, claims: dict[str, Any] | None = None) -> None:
            from ..queueing import count_jobs, read_jobs

            _PAGE_SIZE = 100
            _query = query or {}
            try:
                page = max(1, int((_query.get("page") or ["1"])[0]))
            except (ValueError, TypeError):
                page = 1
            offset = (page - 1) * _PAGE_SIZE
            total = count_jobs(cache_dir)
            total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
            jobs = read_jobs(cache_dir, limit=_PAGE_SIZE, offset=offset, newest_first=True)
            if self._wants_json():
                self._send_json(
                    {
                        "jobs": jobs,
                        "page": page,
                        "total_pages": total_pages,
                        "total": total,
                    }
                )
                return
            page_html = build_history_page(jobs, page=page, total_pages=total_pages)
            self._send_text(page_html, content_type="text/html; charset=utf-8")

        def _handle_healthz(self) -> None:
            from ..queueing import queue_counts

            counts = queue_counts(cache_dir)
            self._send_json({"status": "ok", "queue": counts})

        def _handle_index(self, query: dict, claims: dict[str, Any]) -> None:
            if self._wants_json():
                # Return dashboard stats as JSON
                from ..queueing import queue_counts, read_jobs

                counts = queue_counts(cache_dir)
                recent_jobs = read_jobs(cache_dir, limit=10, newest_first=True)
                workflows_list, _ = handle_list_workflows(workflows_dir)
                worker_info = handle_worker_status(cache_dir)
                roles = self._get_roles(claims)
                self._send_json(
                    {
                        "queue": counts,
                        "workflow_count": len(workflows_list),
                        "worker": worker_info,
                        "recent_jobs": [
                            {
                                "job_id": j.get("job_id"),
                                "status": j.get("status"),
                                "workflow_name": j.get("workflow_name"),
                                "display_name": j.get("display_name"),
                                "created_at": j.get("created_at"),
                            }
                            for j in recent_jobs
                        ],
                        "user": {
                            "identity": self._identity(claims),
                            "roles": roles,
                            "highest_role": highest_role(roles),
                        },
                    }
                )
                return

            sid = query.get("sid", [None])[0]
            file_name = query.get("file", [None])[0]
            workflow_filter = query.get("workflow", [None])[0]
            data = get_index_data(cache_dir, yt_dlp_binary, sid, file_name, workflow_filter)
            workflows, workflow_errors = handle_list_workflows(workflows_dir)
            workflow_names = [str(getattr(wf, "name", "")).strip() for wf in workflows]
            workflow_names = [name for name in workflow_names if name]
            triggers, trigger_errors = handle_list_triggers(_triggers_dir(config))
            trigger_last_seen = trigger_last_seen_by_name(cache_dir)
            trigger_rows: list[dict[str, object]] = []
            for tr in triggers:
                name = str(getattr(tr, "name", "")).strip()
                workflow_name = str(getattr(tr, "workflow", "")).strip()
                if not name or not workflow_name:
                    continue
                trigger_type = str(getattr(tr, "type", "")).strip()
                trigger_cfg = getattr(tr, "config", {})
                if not isinstance(trigger_cfg, dict):
                    trigger_cfg = {}
                next_run_hint = ""
                if trigger_type == "cron":
                    if "interval_seconds" in trigger_cfg:
                        next_run_hint = f"every {trigger_cfg.get('interval_seconds')}s"
                    elif "schedule" in trigger_cfg:
                        next_run_hint = f"cron {trigger_cfg.get('schedule')}"
                elif trigger_type in {"rss_poll", "email_poll", "folder_watch"}:
                    interval_val = trigger_cfg.get("interval_seconds", trigger_cfg.get("interval", ""))
                    if interval_val != "":
                        next_run_hint = f"poll every {interval_val}s"

                recent_runs = 0
                recent_failures = 0
                for job in data["jobs"]:
                    params = job.get("params")
                    if not isinstance(params, dict):
                        continue
                    if str(params.get("_trigger_name", "")).strip() != name:
                        continue
                    recent_runs += 1
                    status = str(job.get("status", ""))
                    if status in {"failed", "dead_letter"}:
                        recent_failures += 1

                trigger_rows.append(
                    {
                        "name": name,
                        "workflow": workflow_name,
                        "type": trigger_type,
                        "enabled": bool(getattr(tr, "enabled", True)),
                        "last_seen": trigger_last_seen.get(name, ""),
                        "recent_runs": recent_runs,
                        "recent_failures": recent_failures,
                        "next_run_hint": next_run_hint,
                    }
                )
            content = render_file_content(data["selected_file"])
            page = build_page(
                data["entries"],
                data["selected_source"],
                data["selected_file"],
                content,
                data["q_counts"],
                data["jobs"],
                w_status=data["w_stat"],
                workflow_filter=workflow_filter,
                configured_workflows=workflow_names,
                configured_triggers=trigger_rows,
                workflow_load_errors=len(workflow_errors),
                trigger_load_errors=len(trigger_errors),
                default_workflow=_default_workflow,
            )
            self._send_text(page, content_type="text/html; charset=utf-8")

        def _handle_raw(self, query: dict) -> None:
            sid = query.get("sid", [None])[0]
            file_name = query.get("file", [None])[0]
            entries = discover_sources(cache_dir, yt_dlp_binary=yt_dlp_binary)
            selected_source = safe_select_source(entries, sid)
            selected_file = safe_select_file(selected_source, file_name) if selected_source else None
            if not selected_file:
                self._send_text("File not found", status=404)
                return

            try:
                payload = selected_file.path.read_bytes()
            except OSError as exc:
                self._send_text(f"Failed to read file: {exc}", status=500)
                return

            content_type = mimetypes.guess_type(selected_file.name)[0] or "text/plain"
            if content_type.startswith("text/") or content_type in {"application/json"}:
                content_type += "; charset=utf-8"
            self._send_bytes(payload, content_type=content_type)

        def _handle_sse(self) -> None:
            from ..queueing import queue_counts, read_jobs

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    counts = queue_counts(cache_dir)
                    recent = read_jobs(cache_dir, limit=5, newest_first=True)
                    recent_data = [
                        {
                            "job_id": j.get("job_id"),
                            "status": j.get("status"),
                            "workflow_name": j.get("workflow_name"),
                            "display_name": j.get("display_name"),
                        }
                        for j in recent
                    ]
                    payload = json.dumps({"counts": counts, "recent": recent_data})
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(2)
            except (OSError, BrokenPipeError):
                pass

        # ── Audit API ────────────────────────────────────────────────────

        def _handle_audit_query(self, query: dict, claims: dict[str, Any]) -> None:
            if not self._check_permission(claims, "audit.read"):
                return
            if audit_logger is None:
                self._send_json({"events": [], "total": 0})
                return
            try:
                limit = min(500, max(1, int((query.get("limit") or ["50"])[0])))
            except (ValueError, TypeError):
                limit = 50
            try:
                offset = max(0, int((query.get("offset") or ["0"])[0]))
            except (ValueError, TypeError):
                offset = 0
            identity = (query.get("identity") or [""])[0]
            action = (query.get("action") or [""])[0]
            resource = (query.get("resource") or [""])[0]
            since = (query.get("since") or [""])[0]
            until = (query.get("until") or [""])[0]

            events = audit_logger.query(
                limit=limit,
                offset=offset,
                identity=identity,
                action=action,
                resource=resource,
                since=since,
                until=until,
            )
            total = audit_logger.count(identity=identity, action=action)
            self._send_json({"events": events, "total": total})

        def _handle_audit_export(self, query: dict, claims: dict[str, Any]) -> None:
            if not self._check_permission(claims, "audit.read"):
                return
            if audit_logger is None:
                self._send_text("", status=204)
                return
            fmt = (query.get("format") or ["json"])[0]
            identity = (query.get("identity") or [""])[0]
            action = (query.get("action") or [""])[0]
            since = (query.get("since") or [""])[0]
            until = (query.get("until") or [""])[0]

            export_data = audit_logger.export(
                fmt=fmt,
                identity=identity,
                action=action,
                since=since,
                until=until,
            )
            if fmt == "csv":
                self._send_text(export_data, content_type="text/csv; charset=utf-8")
            else:
                self._send_text(export_data, content_type="application/json; charset=utf-8")

        def _handle_audit_verify(self, claims: dict[str, Any]) -> None:
            if not self._check_permission(claims, "audit.read"):
                return
            if audit_logger is None:
                self._send_json({"valid": True, "total": 0, "verified": 0, "message": "Audit logging disabled"})
                return
            result = audit_logger.verify_chain()
            self._send_json(result)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            print(f"[serve] {self.address_string()} - {format % args}")

    return Handler
