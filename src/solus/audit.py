"""Audit logging for Solus.

Stores audit events in a separate SQLite database alongside the job queue.
Optionally forwards events to syslog for SIEM integration.
Supports SQLCipher encryption at rest (config-gated via SOLUS_AUDIT_DB_KEY).
Supports HMAC-SHA256 chain signing for tamper detection (config-gated via audit.hmac_key).
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Config-gated encryption key from environment
_AUDIT_DB_KEY = os.environ.get("SOLUS_AUDIT_DB_KEY", "")

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS audit_events (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    identity    TEXT NOT NULL DEFAULT '',
    ip_address  TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL DEFAULT '',
    result      TEXT NOT NULL DEFAULT 'success',
    detail      TEXT NOT NULL DEFAULT '{}',
    session_id  TEXT NOT NULL DEFAULT '',
    prev_hash   TEXT NOT NULL DEFAULT '',
    hmac        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events (timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_identity ON audit_events (identity);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events (action);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLogger:
    """Audit event logger backed by SQLite with optional syslog forwarding."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        enabled: bool = True,
        syslog_addr: str = "",
        retention_days: int = 90,
        hmac_key: str = "",
    ) -> None:
        self.enabled = enabled
        self.cache_dir = cache_dir
        self.retention_days = retention_days
        self._hmac_key = hmac_key
        self._lock = threading.Lock()
        self._syslog_handler: logging.Handler | None = None
        self._db_key = _AUDIT_DB_KEY

        if not self.enabled:
            return

        queue_dir = cache_dir / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = queue_dir / "audit.db"
        self._ensure_schema()

        if syslog_addr:
            self._setup_syslog(syslog_addr)

    def _ensure_schema(self) -> None:
        conn = self._raw_connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _raw_connect(self) -> sqlite3.Connection:
        """Open a connection, applying SQLCipher PRAGMA if key is set."""
        if self._db_key:
            try:
                from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore[import-not-found]

                conn: sqlite3.Connection = sqlcipher.connect(str(self._db_path), timeout=30)
                conn.execute(f"PRAGMA key='{self._db_key}'")
            except ImportError:
                _log.warning("SOLUS_AUDIT_DB_KEY is set but pysqlcipher3 is not installed; using plain SQLite")
                conn = sqlite3.connect(str(self._db_path), timeout=30)
        else:
            conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _connect(self) -> sqlite3.Connection:
        conn = self._raw_connect()
        conn.row_factory = sqlite3.Row
        return conn

    def _setup_syslog(self, addr: str) -> None:
        """Configure syslog forwarding. addr format: ``udp://host:port`` or ``tcp://host:port``."""
        try:
            from logging.handlers import SysLogHandler

            proto = addr.split("://")[0].lower() if "://" in addr else "udp"
            hostport = addr.split("://")[-1] if "://" in addr else addr
            if ":" in hostport:
                host, port_str = hostport.rsplit(":", 1)
                port = int(port_str)
            else:
                host = hostport
                port = 514

            socktype = None
            import socket

            if proto == "tcp":
                socktype = socket.SOCK_STREAM
            else:
                socktype = socket.SOCK_DGRAM

            handler = SysLogHandler(address=(host, port), socktype=socktype)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._syslog_handler = handler
            _log.info("Audit syslog forwarding configured: %s", addr)
        except Exception as exc:
            _log.warning("Failed to configure audit syslog forwarding: %s", exc)

    def log(
        self,
        *,
        identity: str = "",
        ip_address: str = "",
        action: str,
        resource: str = "",
        result: str = "success",
        detail: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> str | None:
        """Record an audit event. Returns the event ID, or None if disabled."""
        if not self.enabled:
            return None

        event_id = uuid.uuid4().hex[:16]
        timestamp = _utc_now()
        detail_json = json.dumps(detail or {})

        with self._lock:
            conn = self._connect()
            try:
                prev_hash = ""
                event_hmac = ""

                if self._hmac_key:
                    # Get hash of previous event for chain
                    row = conn.execute("SELECT id, hmac FROM audit_events ORDER BY rowid DESC LIMIT 1").fetchone()
                    prev_hash = dict(row)["hmac"] if row else hashlib.sha256(b"genesis").hexdigest()

                    # Compute HMAC of this event
                    msg = f"{event_id}|{timestamp}|{identity}|{action}|{resource}|{result}|{prev_hash}"
                    event_hmac = hmac.new(self._hmac_key.encode(), msg.encode(), hashlib.sha256).hexdigest()

                conn.execute(
                    """INSERT INTO audit_events
                    (id, timestamp, identity, ip_address, action, resource, result, detail, session_id, prev_hash, hmac)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id,
                        timestamp,
                        identity,
                        ip_address,
                        action,
                        resource,
                        result,
                        detail_json,
                        session_id,
                        prev_hash,
                        event_hmac,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        if self._syslog_handler:
            msg = f"AUDIT: action={action} identity={identity} resource={resource} result={result} ip={ip_address}"
            record = logging.LogRecord(
                name="solus.audit",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=msg,
                args=(),
                exc_info=None,
            )
            try:
                self._syslog_handler.emit(record)
            except Exception:
                pass

        return event_id

    def query(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        identity: str = "",
        action: str = "",
        resource: str = "",
        since: str = "",
        until: str = "",
    ) -> list[dict[str, Any]]:
        """Query audit events with optional filters."""
        if not self.enabled:
            return []

        conditions: list[str] = []
        params: list[str] = []

        if identity:
            conditions.append("identity = ?")
            params.append(identity)
        if action:
            conditions.append("action = ?")
            params.append(action)
        if resource:
            conditions.append("resource LIKE ?")
            params.append(f"%{resource}%")
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM audit_events WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([str(max(1, limit)), str(max(0, offset))])

        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def count(
        self,
        *,
        identity: str = "",
        action: str = "",
    ) -> int:
        """Count audit events with optional filters."""
        if not self.enabled:
            return 0

        conditions: list[str] = []
        params: list[str] = []

        if identity:
            conditions.append("identity = ?")
            params.append(identity)
        if action:
            conditions.append("action = ?")
            params.append(action)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT COUNT(*) FROM audit_events WHERE {where}"

        conn = self._connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def export(self, fmt: str = "json", **filters: Any) -> str:
        """Export audit events as JSON or CSV string."""
        events = self.query(limit=10000, **filters)

        if fmt == "csv":
            output = io.StringIO()
            if events:
                writer = csv.DictWriter(output, fieldnames=events[0].keys())
                writer.writeheader()
                writer.writerows(events)
            return output.getvalue()

        return json.dumps(events, indent=2)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if "detail" in d:
            try:
                d["detail"] = json.loads(d["detail"])
            except (json.JSONDecodeError, TypeError):
                d["detail"] = {}
        return d

    def verify_chain(self) -> dict[str, Any]:
        """Verify the HMAC chain integrity of all audit events.

        Returns a dict with 'valid' (bool), 'total' (int), 'verified' (int),
        and optionally 'broken_at' (event ID where chain breaks).
        """
        if not self.enabled or not self._hmac_key:
            return {"valid": True, "total": 0, "verified": 0, "message": "HMAC signing not enabled"}

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, timestamp, identity, action, resource, result, prev_hash, hmac "
                "FROM audit_events ORDER BY rowid ASC"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return {"valid": True, "total": 0, "verified": 0}

        expected_prev = hashlib.sha256(b"genesis").hexdigest()
        for row in rows:
            r = dict(row)
            # Verify prev_hash chain
            if r["prev_hash"] != expected_prev:
                return {
                    "valid": False,
                    "total": len(rows),
                    "verified": rows.index(row),
                    "broken_at": r["id"],
                    "message": "Chain link mismatch",
                }
            # Verify HMAC
            msg = f"{r['id']}|{r['timestamp']}|{r['identity']}|{r['action']}|{r['resource']}|{r['result']}|{r['prev_hash']}"
            expected_hmac = hmac.new(self._hmac_key.encode(), msg.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(r["hmac"], expected_hmac):
                return {
                    "valid": False,
                    "total": len(rows),
                    "verified": rows.index(row),
                    "broken_at": r["id"],
                    "message": "HMAC mismatch — possible tampering",
                }
            expected_prev = r["hmac"]

        return {"valid": True, "total": len(rows), "verified": len(rows)}

    def cleanup(self, retention_days: int | None = None) -> int:
        """Delete events older than retention_days. Returns count deleted."""
        if not self.enabled:
            return 0
        days = retention_days if retention_days is not None else self.retention_days
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        conn = self._connect()
        try:
            cursor = conn.execute("DELETE FROM audit_events WHERE timestamp < ?", (cutoff_str,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
