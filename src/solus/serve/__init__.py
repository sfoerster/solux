from __future__ import annotations

import ipaddress
import logging
import shutil
from http.server import ThreadingHTTPServer
from pathlib import Path

from .handler import build_handler
from .sources import FileEntry, SourceEntry, discover_sources
from .templates import render_file_content, build_page

# Backwards-compatible aliases used by tests and external callers
_build_handler = build_handler
_render_file_content = render_file_content
_build_page = build_page

_log = logging.getLogger(__name__)


def _is_non_local_bind(host: str) -> bool:
    value = host.strip().lower()
    if value in {"localhost", "127.0.0.1", "::1", "[::1]"}:
        return False
    if value in {"0.0.0.0", "::", "[::]"}:
        return True
    try:
        ip = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        # Treat non-IP hostnames as potentially non-local.
        return True
    return not ip.is_loopback


def run_serve(
    cache_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    yt_dlp_binary: str | None = None,
    config=None,
    workflows_dir: Path | None = None,
) -> int:
    sec = getattr(config, "security", None) if config is not None else None
    auth_required = bool(getattr(sec, "oidc_require_auth", False))
    if _is_non_local_bind(host) and not auth_required:
        print(
            "WARNING: binding to a non-local interface without OIDC auth. "
            "Set [security].oidc_require_auth=true before exposing this service."
        )

    # Warn at startup if optional external binaries are missing.
    _yt_dlp_bin = yt_dlp_binary or "yt-dlp"
    for _bin_name in (_yt_dlp_bin, "ffmpeg"):
        if not shutil.which(_bin_name):
            _log.warning("startup: binary %r not found in PATH — some modules may fail", _bin_name)

    # Initialize audit logger
    audit_logger = None
    audit_cfg = getattr(config, "audit", None) if config is not None else None
    if audit_cfg is None or getattr(audit_cfg, "enabled", True):
        from ..audit import AuditLogger

        audit_logger = AuditLogger(
            cache_dir,
            enabled=getattr(audit_cfg, "enabled", True) if audit_cfg else True,
            syslog_addr=getattr(audit_cfg, "syslog_addr", "") if audit_cfg else "",
            retention_days=getattr(audit_cfg, "retention_days", 90) if audit_cfg else 90,
        )

    handler = build_handler(
        cache_dir,
        yt_dlp_binary=yt_dlp_binary,
        config=config,
        workflows_dir=workflows_dir,
        audit_logger=audit_logger,
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Serving solus output UI at http://{host}:{port}")
    print(f"Cache root: {cache_dir}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
    return 0


__all__ = ["run_serve", "discover_sources", "FileEntry", "SourceEntry"]
