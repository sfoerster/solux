from __future__ import annotations

import json
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from solux.queueing import read_jobs
from solux.serve import _build_handler, _build_page


@pytest.fixture()
def server(tmp_path: Path):
    """Start a test HTTP server on an ephemeral port backed by tmp_path as cache_dir."""
    from http.server import ThreadingHTTPServer

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    handler_cls = _build_handler(cache_dir, yt_dlp_binary=None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    class Info:
        def __init__(self):
            self.cache_dir = cache_dir
            self.port = port
            self.httpd = httpd

    info = Info()
    yield info
    httpd.shutdown()


def _post_form(
    port: int,
    path: str,
    body: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = HTTPConnection("127.0.0.1", port)
    req_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        req_headers.update(headers)
    conn.request(
        "POST",
        path,
        body=body.encode("utf-8"),
        headers=req_headers,
    )
    resp = conn.getresponse()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    data = resp.read()
    conn.close()
    return resp.status, headers, data


def _post_multipart(
    port: int, path: str, fields: dict[str, str], file_field: str, filename: str, file_data: bytes
) -> tuple[int, dict[str, str], bytes]:
    boundary = "----TestBoundary12345"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'------TestBoundary12345\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode(
                "utf-8"
            )
        )
    parts.append(
        f"------TestBoundary12345\r\n"
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
        + file_data
        + b"\r\n"
    )
    parts.append(b"------TestBoundary12345--\r\n")
    body = b"".join(parts)

    conn = HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST",
        path,
        body=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary=----TestBoundary12345",
            "Content-Length": str(len(body)),
        },
    )
    resp = conn.getresponse()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    data = resp.read()
    conn.close()
    return resp.status, headers, data


def _post_json(port: int, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload).encode("utf-8")
    conn = HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST",
        path,
        body=body,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )
    resp = conn.getresponse()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    data = resp.read()
    conn.close()
    return resp.status, headers, data


def test_ingest_url_enqueues_and_redirects(server, monkeypatch):
    monkeypatch.setattr("solux.serve.api.ensure_background_worker", lambda _: False)
    status, headers, _ = _post_form(
        server.port, "/ingest-url", "url=https%3A%2F%2Fexample.com%2Faudio.mp3&mode=tldr&format=text"
    )
    assert status == 303
    assert headers["location"] == "/"
    jobs = read_jobs(server.cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "https://example.com/audio.mp3"
    assert jobs[0]["mode"] == "tldr"
    assert jobs[0]["format"] == "text"
    assert jobs[0]["status"] == "pending"


def test_ingest_url_empty_returns_400(server):
    status, _, body = _post_form(server.port, "/ingest-url", "url=&mode=full&format=markdown")
    assert status == 400
    assert b"Missing url" in body


def test_ingest_file_saves_and_enqueues(server, monkeypatch):
    monkeypatch.setattr("solux.serve.api.ensure_background_worker", lambda _: False)
    fake_audio = b"\x00" * 256
    status, headers, _ = _post_multipart(
        server.port,
        "/ingest-file",
        fields={"mode": "full", "format": "markdown"},
        file_field="file",
        filename="episode.mp3",
        file_data=fake_audio,
    )
    assert status == 303
    assert headers["location"] == "/"

    uploads_dir = server.cache_dir / "uploads"
    assert uploads_dir.exists()
    uploaded_files = list(uploads_dir.iterdir())
    assert len(uploaded_files) == 1
    assert uploaded_files[0].name.endswith("-episode.mp3")
    assert uploaded_files[0].read_bytes() == fake_audio

    jobs = read_jobs(server.cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["source"] == str(uploaded_files[0])
    assert jobs[0]["status"] == "pending"


def test_ingest_file_json_returns_job_id(server, monkeypatch):
    """When Accept: application/json, ingest-file returns a JSON body with job_id."""
    monkeypatch.setattr("solux.serve.api.ensure_background_worker", lambda _: False)
    fake_pdf = b"%PDF-1.4 fake content"
    boundary = "----TestBoundary12345"
    parts: list[bytes] = []
    for name, value in [("mode", "full"), ("format", "markdown"), ("workflow", "clinical_doc_triage")]:
        parts.append(
            f'------TestBoundary12345\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode(
                "utf-8"
            )
        )
    parts.append(
        f"------TestBoundary12345\r\n"
        f'Content-Disposition: form-data; name="file"; filename="report.pdf"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
        + fake_pdf
        + b"\r\n"
    )
    parts.append(b"------TestBoundary12345--\r\n")
    body = b"".join(parts)

    conn = HTTPConnection("127.0.0.1", server.port)
    conn.request(
        "POST",
        "/ingest-file",
        body=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary=----TestBoundary12345",
            "Content-Length": str(len(body)),
            "Accept": "application/json",
        },
    )
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read())
    conn.close()
    assert data["ok"] is True
    assert data["filename"] == "report.pdf"
    assert data["workflow"] == "clinical_doc_triage"
    assert "job_id" in data
    assert data["job_id"] is not None

    # Verify the job_id actually matches a real queued job
    jobs = read_jobs(server.cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == data["job_id"]


def test_handle_ingest_file_returns_job_id_tuple(tmp_path):
    """handle_ingest_file returns (True, job_id) tuple."""
    from solux.serve.api import handle_ingest_file

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    ok, job_id = handle_ingest_file(
        cache_dir,
        file_data=b"test file content",
        file_name="test.pdf",
        mode="full",
        output_format="markdown",
        workflow_name="clinical_doc_triage",
    )
    assert ok is True
    assert job_id is not None
    assert isinstance(job_id, str)
    assert len(job_id) > 0

    # Verify the job_id matches the queued job
    jobs = read_jobs(cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == job_id


def test_ingest_file_empty_returns_400(server):
    boundary = "----TestBoundary12345"
    body = (
        f"------TestBoundary12345\r\n"
        f'Content-Disposition: form-data; name="mode"\r\n\r\n'
        f"full\r\n"
        f"------TestBoundary12345--\r\n"
    ).encode("utf-8")

    conn = HTTPConnection("127.0.0.1", server.port)
    conn.request(
        "POST",
        "/ingest-file",
        body=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary=----TestBoundary12345",
            "Content-Length": str(len(body)),
        },
    )
    resp = conn.getresponse()
    assert resp.status == 400
    assert b"No file uploaded" in resp.read()
    conn.close()


def test_index_page_contains_ingest_forms(server):
    conn = HTTPConnection("127.0.0.1", server.port)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    assert resp.status == 200
    assert 'action="/ingest-url"' in body
    assert 'action="/ingest-file"' in body
    assert "Ingest new source" in body
    assert "Queue URL" in body
    assert "Upload &amp; queue" in body
    assert 'name="workflow"' in body
    assert 'class="ingest-row"' in body
    assert "Configured workflows" in body
    assert "Configured triggers" in body


def test_index_page_contains_worker_controls(server):
    conn = HTTPConnection("127.0.0.1", server.port)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    assert resp.status == 200
    assert 'action="/worker-start"' in body
    assert 'action="/worker-stop"' in body
    assert "Worker:" in body


def test_worker_status_returns_json(server):
    conn = HTTPConnection("127.0.0.1", server.port)
    conn.request("GET", "/worker-status")
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    assert resp.status == 200
    data = json.loads(body)
    assert data["status"] in ("running", "stopped")
    assert "pid" in data


def test_workflow_editor_prefills_builtin_yaml(server):
    conn = HTTPConnection("127.0.0.1", server.port)
    conn.request("GET", "/workflow/audio_summary")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    assert resp.status == 200
    assert 'name="yaml"' in body
    assert "name: audio_summary" in body


def test_worker_start_redirects(server, monkeypatch):
    monkeypatch.setattr(
        "solux.serve.api.start_background_worker",
        lambda cache_dir, **kw: (True, 12345, "started"),
    )
    status, headers, _ = _post_form(server.port, "/worker-start", "")
    assert status == 303
    assert headers["location"] == "/"


def test_worker_start_already_running_redirects(server, monkeypatch):
    monkeypatch.setattr(
        "solux.serve.api.start_background_worker",
        lambda cache_dir, **kw: (False, 99, "already-running"),
    )
    status, headers, _ = _post_form(server.port, "/worker-start", "")
    assert status == 303
    assert headers["location"] == "/"


def test_worker_stop_not_running_redirects(server, monkeypatch):
    monkeypatch.setattr(
        "solux.serve.api.stop_background_worker",
        lambda cache_dir: (False, "not-running"),
    )
    status, headers, _ = _post_form(server.port, "/worker-stop", "")
    assert status == 303
    assert headers["location"] == "/"


def test_worker_stop_stopped_redirects(server, monkeypatch):
    monkeypatch.setattr(
        "solux.serve.api.stop_background_worker",
        lambda cache_dir: (True, "stopped"),
    )
    status, headers, _ = _post_form(server.port, "/worker-stop", "")
    assert status == 303
    assert headers["location"] == "/"


def test_worker_stop_timeout_returns_504(server, monkeypatch):
    monkeypatch.setattr(
        "solux.serve.api.stop_background_worker",
        lambda cache_dir: (False, "timeout"),
    )
    status, _, body = _post_form(server.port, "/worker-stop", "")
    assert status == 504
    assert b"timeout" in body


def test_worker_restart_redirects_to_next(server, monkeypatch):
    monkeypatch.setattr(
        "solux.serve.api.stop_background_worker",
        lambda cache_dir: (True, "stopped"),
    )
    monkeypatch.setattr(
        "solux.serve.api.start_background_worker",
        lambda cache_dir, **kw: (True, 12345, "started"),
    )
    status, headers, _ = _post_form(server.port, "/worker-restart", "next=%2Ftriggers")
    assert status == 303
    assert headers["location"] == "/triggers"


def test_worker_restart_timeout_returns_504(server, monkeypatch):
    monkeypatch.setattr(
        "solux.serve.api.stop_background_worker",
        lambda cache_dir: (False, "timeout"),
    )
    status, _, body = _post_form(server.port, "/worker-restart", "next=%2Ftriggers")
    assert status == 504
    assert b"timeout" in body


def test_post_rejects_cross_site_origin(server) -> None:
    status, _, body = _post_form(
        server.port,
        "/ingest-url",
        "url=https%3A%2F%2Fexample.com%2Faudio.mp3",
        headers={"Origin": "http://evil.example"},
    )
    assert status == 403
    assert b"CSRF" in body
    assert read_jobs(server.cache_dir) == []


def test_trigger_webhook_honors_upload_size_limit(server, monkeypatch):
    monkeypatch.setattr("solux.serve.handler._MAX_WEBHOOK_BYTES", 10)
    status, _, body = _post_json(
        server.port,
        "/api/trigger/webpage_summary",
        {"source": "https://example.com/very-long-url-that-exceeds-limit"},
    )
    assert status == 413
    assert b"Payload too large" in body


def test_trigger_webhook_resolves_workflow_from_handler_workflows_dir(tmp_path: Path) -> None:
    from http.server import ThreadingHTTPServer

    cache_dir = tmp_path / "cache"
    workflows_dir = tmp_path / "wf"
    cache_dir.mkdir()
    workflows_dir.mkdir()
    (workflows_dir / "custom_hook.yaml").write_text(
        "name: custom_hook\ndescription: test\nsteps:\n  - name: clean\n    type: transform.text_clean\n    config: {}\n",
        encoding="utf-8",
    )

    handler_cls = _build_handler(cache_dir, yt_dlp_binary=None, workflows_dir=workflows_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _post_json(port, "/api/trigger/custom_hook", {"source": "https://example.com"})
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "queued"

        jobs = read_jobs(cache_dir)
        assert len(jobs) == 1
        assert jobs[0]["workflow_name"] == "custom_hook"
    finally:
        httpd.shutdown()
