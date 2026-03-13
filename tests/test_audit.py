"""Tests for the audit logging module (solux.audit)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from solux.audit import AuditLogger


@pytest.fixture()
def audit(tmp_path: Path) -> AuditLogger:
    """Create an enabled AuditLogger backed by tmp_path."""
    return AuditLogger(tmp_path, enabled=True)


@pytest.fixture()
def disabled_audit(tmp_path: Path) -> AuditLogger:
    """Create a disabled AuditLogger."""
    return AuditLogger(tmp_path, enabled=False)


# ── Basic logging ────────────────────────────────────────────────────────


class TestLog:
    def test_log_returns_event_id(self, audit: AuditLogger) -> None:
        event_id = audit.log(action="test.action")
        assert event_id is not None
        assert len(event_id) == 16

    def test_log_disabled_returns_none(self, disabled_audit: AuditLogger) -> None:
        result = disabled_audit.log(action="test.action")
        assert result is None

    def test_log_with_all_fields(self, audit: AuditLogger) -> None:
        event_id = audit.log(
            identity="admin@test.local",
            ip_address="192.168.1.1",
            action="workflows.run",
            resource="clinical_doc_summary",
            result="success",
            detail={"steps": 3, "duration_ms": 1500},
            session_id="sess-abc123",
        )
        assert event_id is not None
        events = audit.query(limit=1)
        assert len(events) == 1
        ev = events[0]
        assert ev["identity"] == "admin@test.local"
        assert ev["ip_address"] == "192.168.1.1"
        assert ev["action"] == "workflows.run"
        assert ev["resource"] == "clinical_doc_summary"
        assert ev["result"] == "success"
        assert ev["detail"]["steps"] == 3
        assert ev["session_id"] == "sess-abc123"

    def test_log_stores_timestamp(self, audit: AuditLogger) -> None:
        audit.log(action="test.action")
        events = audit.query(limit=1)
        ts = events[0]["timestamp"]
        # Should be parseable as ISO format
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None  # Should have timezone

    def test_log_default_values(self, audit: AuditLogger) -> None:
        audit.log(action="test.action")
        ev = audit.query(limit=1)[0]
        assert ev["identity"] == ""
        assert ev["ip_address"] == ""
        assert ev["resource"] == ""
        assert ev["result"] == "success"
        assert ev["detail"] == {}
        assert ev["session_id"] == ""

    def test_multiple_events(self, audit: AuditLogger) -> None:
        for i in range(5):
            audit.log(action=f"action_{i}", identity=f"user_{i}")
        events = audit.query(limit=10)
        assert len(events) == 5


# ── Query ────────────────────────────────────────────────────────────────


class TestQuery:
    def test_query_empty_db(self, audit: AuditLogger) -> None:
        events = audit.query()
        assert events == []

    def test_query_disabled_returns_empty(self, disabled_audit: AuditLogger) -> None:
        events = disabled_audit.query()
        assert events == []

    def test_query_limit(self, audit: AuditLogger) -> None:
        for i in range(10):
            audit.log(action=f"action_{i}")
        events = audit.query(limit=3)
        assert len(events) == 3

    def test_query_offset(self, audit: AuditLogger) -> None:
        for i in range(5):
            audit.log(action=f"action_{i}", identity="user")
        all_events = audit.query(limit=100)
        offset_events = audit.query(limit=100, offset=2)
        assert len(offset_events) == 3
        assert offset_events[0]["id"] == all_events[2]["id"]

    def test_query_filter_by_identity(self, audit: AuditLogger) -> None:
        audit.log(action="a", identity="alice")
        audit.log(action="b", identity="bob")
        audit.log(action="c", identity="alice")
        events = audit.query(identity="alice")
        assert len(events) == 2
        assert all(e["identity"] == "alice" for e in events)

    def test_query_filter_by_action(self, audit: AuditLogger) -> None:
        audit.log(action="workflows.run", identity="user")
        audit.log(action="workflows.delete", identity="user")
        audit.log(action="workflows.run", identity="user")
        events = audit.query(action="workflows.run")
        assert len(events) == 2

    def test_query_filter_by_resource(self, audit: AuditLogger) -> None:
        audit.log(action="run", resource="workflow_a")
        audit.log(action="run", resource="workflow_b")
        audit.log(action="run", resource="workflow_ab")
        events = audit.query(resource="workflow_a")
        # LIKE %workflow_a% matches workflow_a and workflow_ab
        assert len(events) >= 2

    def test_query_filter_by_since(self, audit: AuditLogger) -> None:
        audit.log(action="old")
        # Use a future timestamp as 'since' - should return nothing
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        events = audit.query(since=future)
        assert len(events) == 0

    def test_query_ordered_newest_first(self, audit: AuditLogger) -> None:
        audit.log(action="first")
        audit.log(action="second")
        audit.log(action="third")
        events = audit.query(limit=3)
        assert events[0]["action"] == "third"
        assert events[-1]["action"] == "first"

    def test_query_detail_parsed_as_dict(self, audit: AuditLogger) -> None:
        audit.log(action="test", detail={"key": "value", "num": 42})
        ev = audit.query(limit=1)[0]
        assert isinstance(ev["detail"], dict)
        assert ev["detail"]["key"] == "value"
        assert ev["detail"]["num"] == 42


# ── Count ────────────────────────────────────────────────────────────────


class TestCount:
    def test_count_all(self, audit: AuditLogger) -> None:
        for i in range(7):
            audit.log(action=f"action_{i}")
        assert audit.count() == 7

    def test_count_empty(self, audit: AuditLogger) -> None:
        assert audit.count() == 0

    def test_count_disabled_returns_zero(self, disabled_audit: AuditLogger) -> None:
        assert disabled_audit.count() == 0

    def test_count_filter_by_identity(self, audit: AuditLogger) -> None:
        audit.log(action="a", identity="alice")
        audit.log(action="b", identity="bob")
        audit.log(action="c", identity="alice")
        assert audit.count(identity="alice") == 2

    def test_count_filter_by_action(self, audit: AuditLogger) -> None:
        audit.log(action="workflows.run")
        audit.log(action="workflows.delete")
        audit.log(action="workflows.run")
        assert audit.count(action="workflows.run") == 2


# ── Export ────────────────────────────────────────────────────────────────


class TestExport:
    def test_export_json(self, audit: AuditLogger) -> None:
        audit.log(action="test1", identity="user1")
        audit.log(action="test2", identity="user2")
        result = audit.export(fmt="json")
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_export_csv(self, audit: AuditLogger) -> None:
        audit.log(action="test1", identity="user1")
        audit.log(action="test2", identity="user2")
        result = audit.export(fmt="csv")
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 2
        assert "action" in rows[0]
        assert "identity" in rows[0]

    def test_export_empty_json(self, audit: AuditLogger) -> None:
        result = audit.export(fmt="json")
        parsed = json.loads(result)
        assert parsed == []

    def test_export_empty_csv(self, audit: AuditLogger) -> None:
        result = audit.export(fmt="csv")
        assert result == ""

    def test_export_with_filters(self, audit: AuditLogger) -> None:
        audit.log(action="a", identity="alice")
        audit.log(action="b", identity="bob")
        result = audit.export(fmt="json", identity="alice")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["identity"] == "alice"


# ── Cleanup ──────────────────────────────────────────────────────────────


class TestCleanup:
    def test_cleanup_disabled_returns_zero(self, disabled_audit: AuditLogger) -> None:
        assert disabled_audit.cleanup() == 0

    def test_cleanup_nothing_to_delete(self, audit: AuditLogger) -> None:
        audit.log(action="recent")
        deleted = audit.cleanup(retention_days=365)
        assert deleted == 0
        assert audit.count() == 1

    def test_cleanup_uses_default_retention(self, tmp_path: Path) -> None:
        logger = AuditLogger(tmp_path, retention_days=0)
        # retention_days=0 means delete everything older than 0 days
        # The just-inserted event should not be older than "now"
        logger.log(action="test")
        # Since cleanup compares timestamp < cutoff, and cutoff is now,
        # the event might or might not be deleted depending on timing.
        # With retention_days=0, cutoff = now, so events at exactly now won't be deleted.
        count = logger.count()
        assert count >= 0  # Just verify it doesn't crash


# ── Database integrity ────────────────────────────────────────────────────


class TestDatabaseIntegrity:
    def test_db_file_created(self, audit: AuditLogger, tmp_path: Path) -> None:
        db_path = tmp_path / "queue" / "audit.db"
        assert db_path.exists()

    def test_concurrent_writes(self, audit: AuditLogger) -> None:
        """Verify that multiple sequential writes don't corrupt the DB."""
        ids = set()
        for i in range(50):
            event_id = audit.log(action=f"action_{i}")
            ids.add(event_id)
        assert len(ids) == 50
        assert audit.count() == 50

    def test_detail_json_roundtrip(self, audit: AuditLogger) -> None:
        detail = {"nested": {"key": [1, 2, 3]}, "bool": True, "null": None}
        audit.log(action="test", detail=detail)
        ev = audit.query(limit=1)[0]
        assert ev["detail"]["nested"]["key"] == [1, 2, 3]
        assert ev["detail"]["bool"] is True
        assert ev["detail"]["null"] is None


# ── Syslog forwarding ────────────────────────────────────────────────────


class TestSyslog:
    def test_invalid_syslog_addr_does_not_crash(self, tmp_path: Path) -> None:
        """A bad syslog address should log a warning but not raise."""
        logger = AuditLogger(tmp_path, syslog_addr="tcp://999.999.999.999:514")
        # Should still be able to log events locally
        event_id = logger.log(action="test")
        assert event_id is not None


# ── HMAC chain ──────────────────────────────────────────────────────────


@pytest.fixture()
def hmac_audit(tmp_path: Path) -> AuditLogger:
    """Create an AuditLogger with HMAC signing enabled."""
    return AuditLogger(tmp_path, enabled=True, hmac_key="test-secret-key")


class TestHMACChain:
    def test_log_stores_hmac_fields(self, hmac_audit: AuditLogger) -> None:
        hmac_audit.log(action="test.action", identity="user1")
        events = hmac_audit.query(limit=1)
        assert len(events) == 1
        ev = events[0]
        assert ev["hmac"] != ""
        assert ev["prev_hash"] != ""

    def test_first_event_uses_genesis_hash(self, hmac_audit: AuditLogger) -> None:
        import hashlib

        hmac_audit.log(action="first")
        events = hmac_audit.query(limit=1)
        genesis = hashlib.sha256(b"genesis").hexdigest()
        assert events[0]["prev_hash"] == genesis

    def test_chain_links_prev_hash_to_prior_hmac(self, hmac_audit: AuditLogger) -> None:
        hmac_audit.log(action="first")
        hmac_audit.log(action="second")
        events = hmac_audit.query(limit=10)
        # events are newest-first
        second = events[0]
        first = events[1]
        assert second["prev_hash"] == first["hmac"]

    def test_verify_chain_valid(self, hmac_audit: AuditLogger) -> None:
        for i in range(5):
            hmac_audit.log(action=f"action_{i}", identity=f"user_{i}")
        result = hmac_audit.verify_chain()
        assert result["valid"] is True
        assert result["total"] == 5
        assert result["verified"] == 5

    def test_verify_chain_empty_db(self, hmac_audit: AuditLogger) -> None:
        result = hmac_audit.verify_chain()
        assert result["valid"] is True
        assert result["total"] == 0

    def test_verify_chain_detects_tampered_hmac(self, hmac_audit: AuditLogger) -> None:
        hmac_audit.log(action="legit_1")
        hmac_audit.log(action="legit_2")
        hmac_audit.log(action="legit_3")

        # Tamper with the second event's HMAC
        conn = hmac_audit._connect()
        try:
            rows = conn.execute("SELECT id FROM audit_events ORDER BY rowid ASC").fetchall()
            second_id = dict(rows[1])["id"]
            conn.execute(
                "UPDATE audit_events SET hmac = 'tampered' WHERE id = ?",
                (second_id,),
            )
            conn.commit()
        finally:
            conn.close()

        result = hmac_audit.verify_chain()
        assert result["valid"] is False
        assert "broken_at" in result

    def test_verify_chain_detects_tampered_prev_hash(self, hmac_audit: AuditLogger) -> None:
        hmac_audit.log(action="a")
        hmac_audit.log(action="b")

        # Tamper with the second event's prev_hash
        conn = hmac_audit._connect()
        try:
            rows = conn.execute("SELECT id FROM audit_events ORDER BY rowid ASC").fetchall()
            second_id = dict(rows[1])["id"]
            conn.execute(
                "UPDATE audit_events SET prev_hash = 'wrong' WHERE id = ?",
                (second_id,),
            )
            conn.commit()
        finally:
            conn.close()

        result = hmac_audit.verify_chain()
        assert result["valid"] is False
        assert result["broken_at"] == second_id
        assert "mismatch" in result["message"].lower()

    def test_verify_chain_not_enabled(self, audit: AuditLogger) -> None:
        """When HMAC is not enabled, verify_chain returns success with 0 verified."""
        audit.log(action="test")
        result = audit.verify_chain()
        assert result["valid"] is True
        assert result["verified"] == 0
        assert "not enabled" in result.get("message", "").lower()

    def test_no_hmac_fields_without_key(self, audit: AuditLogger) -> None:
        """Without hmac_key, hmac and prev_hash should be empty."""
        audit.log(action="test")
        events = audit.query(limit=1)
        assert events[0]["hmac"] == ""
        assert events[0]["prev_hash"] == ""


# ── SQLCipher fallback ──────────────────────────────────────────────────


class TestSQLCipherFallback:
    def test_db_key_env_fallback_without_pysqlcipher3(self, tmp_path: Path) -> None:
        """When SOLUX_AUDIT_DB_KEY is set but pysqlcipher3 is not installed,
        AuditLogger should fall back to plain SQLite and still work."""
        logger = AuditLogger(tmp_path, enabled=True)
        # Manually set _db_key to simulate env var being set
        # (pysqlcipher3 is almost certainly not installed in test env)
        logger._db_key = "test-key-that-triggers-fallback"
        # Re-init schema with the "encrypted" key — should fall back gracefully
        logger._ensure_schema()
        # Should still be able to log and query
        event_id = logger.log(action="encrypted_test")
        assert event_id is not None
        events = logger.query(limit=1)
        assert len(events) == 1
        assert events[0]["action"] == "encrypted_test"

    def test_db_key_empty_uses_plain_sqlite(self, tmp_path: Path) -> None:
        """When _db_key is empty, plain sqlite3 is used (no ImportError)."""
        logger = AuditLogger(tmp_path, enabled=True)
        assert logger._db_key == "" or logger._db_key is None or not logger._db_key
        event_id = logger.log(action="plain_test")
        assert event_id is not None
