"""
SQLite-backed job queue database.

Implements the same public API as queueing.py's job operations, but backed by
SQLite for atomicity and crash recovery instead of fragile JSON files.

Auto-migrates from jobs.json on first startup if the file exists.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    source      TEXT NOT NULL,
    source_id   TEXT,
    display_name TEXT,
    params      TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    output_path TEXT,
    error       TEXT,
    traceback   TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    next_retry_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

_RETRY_MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN retry_count INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN max_retries INTEGER DEFAULT 3",
    "ALTER TABLE jobs ADD COLUMN next_retry_at TEXT",
]

_JOB_COLS = (
    "job_id",
    "workflow_name",
    "source",
    "source_id",
    "display_name",
    "params",
    "status",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "output_path",
    "error",
    "traceback",
    "retry_count",
    "max_retries",
    "next_retry_at",
)


def _db_path(cache_dir: Path) -> Path:
    q = cache_dir / "queue"
    q.mkdir(parents=True, exist_ok=True)
    return q / "jobs.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect(cache_dir: Path):
    db = _db_path(cache_dir)
    conn = sqlite3.connect(str(db), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    # Apply retry column migrations (idempotent - ignore errors if column exists)
    for migration in _RETRY_MIGRATIONS:
        try:
            conn.execute(migration)
            conn.commit()
        except sqlite3.OperationalError:
            pass
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    d = {k: v for k, v in dict(row).items() if v is not None}
    # Deserialize params JSON blob
    try:
        d["params"] = json.loads(d.get("params") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["params"] = {}
    # Add backwards-compat flat fields from params
    params = d["params"]
    if "mode" not in d and "mode" in params:
        d["mode"] = params["mode"]
    if "format" not in d and "format" in params:
        d["format"] = params["format"]
    if "timestamps" not in d and "timestamps" in params:
        d["timestamps"] = bool(params.get("timestamps", False))
    if "no_cache" not in d and "no_cache" in params:
        d["no_cache"] = bool(params.get("no_cache", False))
    if "model" not in d and "model" in params:
        d["model"] = params["model"]
    return d


def _ensure_schema(cache_dir: Path) -> None:
    """Create schema and auto-migrate from jobs.json if present."""
    db = _db_path(cache_dir)
    conn = sqlite3.connect(str(db), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    # Apply retry column migrations (idempotent)
    for migration in _RETRY_MIGRATIONS:
        try:
            conn.execute(migration)
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Auto-migrate from jobs.json
    json_path = db.parent / "jobs.json"
    migrated_path = db.parent / "jobs.json.migrated"
    if json_path.exists() and not migrated_path.exists():
        _migrate_from_json(conn, json_path)
        try:
            json_path.rename(migrated_path)
        except OSError:
            pass
    conn.close()


def _migrate_from_json(conn: sqlite3.Connection, json_path: Path) -> None:
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[db] Migration: could not read {json_path}: {exc}", file=sys.stderr)
        return
    if not isinstance(raw, list):
        return

    now = _utc_now()
    migrated = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("job_id") or uuid.uuid4().hex[:12])
        # Check not already in DB
        existing = conn.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if existing:
            continue
        params = item.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        # Fill params from legacy flat fields
        for key in ("mode", "format", "timestamps", "no_cache", "model"):
            if key not in params and key in item:
                params[key] = item[key]
        conn.execute(
            """INSERT OR IGNORE INTO jobs
            (job_id, workflow_name, source, source_id, display_name, params,
             status, created_at, updated_at, started_at, finished_at, output_path, error, traceback)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                str(item.get("workflow_name") or "audio_summary"),
                str(item.get("source") or ""),
                item.get("source_id"),
                item.get("display_name"),
                json.dumps(params),
                str(item.get("status") or "pending"),
                str(item.get("created_at") or now),
                str(item.get("updated_at") or now),
                item.get("started_at"),
                item.get("finished_at"),
                item.get("output_path"),
                item.get("error"),
                item.get("traceback"),
            ),
        )
        migrated += 1
    conn.commit()
    if migrated:
        print(f"[db] Migrated {migrated} job(s) from {json_path}", file=sys.stderr)


def db_read_jobs(
    cache_dir: Path,
    *,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = False,
) -> list[dict[str, Any]]:
    _ensure_schema(cache_dir)
    with _connect(cache_dir) as conn:
        order = "DESC" if newest_first else "ASC"
        _offset = max(0, int(offset))
        if limit is not None and limit > 0:
            rows = conn.execute(
                f"SELECT * FROM jobs ORDER BY created_at {order} LIMIT ? OFFSET ?",
                (int(limit), _offset),
            ).fetchall()
        elif _offset > 0:
            rows = conn.execute(
                f"SELECT * FROM jobs ORDER BY created_at {order} LIMIT -1 OFFSET ?",
                (_offset,),
            ).fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM jobs ORDER BY created_at {order}").fetchall()
    return [_row_to_job(r) for r in rows]


def db_read_job(cache_dir: Path, job_id: str) -> dict[str, Any] | None:
    _ensure_schema(cache_dir)
    with _connect(cache_dir) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def db_count_jobs(cache_dir: Path) -> int:
    _ensure_schema(cache_dir)
    with _connect(cache_dir) as conn:
        row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    return row[0] if row else 0


def db_enqueue_jobs(
    cache_dir: Path,
    sources: list[str],
    *,
    workflow_name: str = "audio_summary",
    params: dict[str, Any] | None = None,
    mode: str = "full",
    output_format: str = "markdown",
    timestamps: bool = False,
    no_cache: bool = False,
    model: str | None = None,
) -> list[dict[str, Any]]:
    _ensure_schema(cache_dir)
    effective_params = dict(params or {})
    effective_params.setdefault("mode", mode)
    effective_params.setdefault("format", output_format)
    effective_params.setdefault("timestamps", timestamps)
    effective_params.setdefault("no_cache", no_cache)
    if model is not None:
        effective_params.setdefault("model", model)

    now = _utc_now()
    created: list[dict[str, Any]] = []
    with _connect(cache_dir) as conn:
        for source in sources:
            job_id = uuid.uuid4().hex[:12]
            conn.execute(
                """INSERT INTO jobs
                (job_id, workflow_name, source, params, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    job_id,
                    workflow_name,
                    source,
                    json.dumps(effective_params),
                    "pending",
                    now,
                    now,
                ),
            )
            job: dict[str, Any] = {
                "job_id": job_id,
                "workflow_name": workflow_name,
                "source": source,
                "params": dict(effective_params),
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            }
            # Backwards-compat flat fields
            for key in ("mode", "format", "timestamps", "no_cache"):
                if key in effective_params:
                    job[key] = effective_params[key]
            if effective_params.get("model") is not None:
                job["model"] = effective_params["model"]
            created.append(job)
    return created


def db_claim_next_pending_job(cache_dir: Path) -> dict[str, Any] | None:
    _ensure_schema(cache_dir)
    now = _utc_now()
    with _connect(cache_dir) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM jobs WHERE status='pending'
               AND (next_retry_at IS NULL OR next_retry_at <= ?)
               ORDER BY created_at LIMIT 1""",
            (now,),
        ).fetchone()
        if row is None:
            return None
        job_id = row["job_id"]
        conn.execute(
            "UPDATE jobs SET status='processing', started_at=?, updated_at=? WHERE job_id=?",
            (now, now, job_id),
        )
        # Re-fetch updated row
        updated = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    return _row_to_job(updated)


def db_update_job(cache_dir: Path, job_id: str, **updates: Any) -> bool:
    _ensure_schema(cache_dir)
    now = _utc_now()
    with _connect(cache_dir) as conn:
        existing = conn.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not existing:
            return False
        set_clauses = []
        values = []
        for key, value in updates.items():
            if key == "params" and isinstance(value, dict):
                value = json.dumps(value)
            set_clauses.append(f"{key}=?")
            values.append(value)
        set_clauses.append("updated_at=?")
        values.append(now)
        values.append(job_id)
        conn.execute(
            f"UPDATE jobs SET {', '.join(set_clauses)} WHERE job_id=?",
            values,
        )
    return True


def db_queue_counts(cache_dir: Path) -> dict[str, int]:
    _ensure_schema(cache_dir)
    with _connect(cache_dir) as conn:
        rows = conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status").fetchall()
    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0, "dead_letter": 0}
    for row in rows:
        status = str(row["status"])
        if status in counts:
            counts[status] = int(row["cnt"])
    return counts


def db_retry_failed_jobs(
    cache_dir: Path,
    job_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Reset failed/dead-letter jobs back to pending for retry."""
    _ensure_schema(cache_dir)
    now = _utc_now()
    with _connect(cache_dir) as conn:
        if job_ids is not None:
            placeholders = ",".join("?" * len(job_ids))
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ('failed', 'dead_letter') AND job_id IN ({placeholders})",
                job_ids,
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs WHERE status IN ('failed', 'dead_letter')").fetchall()

        reset = []
        for row in rows:
            job_id = row["job_id"]
            conn.execute(
                """UPDATE jobs SET status='pending', error=NULL, traceback=NULL,
                   started_at=NULL, finished_at=NULL, updated_at=?
                   WHERE job_id=?""",
                (now, job_id),
            )
            updated = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            reset.append(_row_to_job(updated))
    return reset


def db_reset_processing_jobs(cache_dir: Path) -> int:
    _ensure_schema(cache_dir)
    now = _utc_now()
    with _connect(cache_dir) as conn:
        result = conn.execute(
            "UPDATE jobs SET status='pending', started_at=NULL, updated_at=? WHERE status='processing'",
            (now,),
        )
    return int(result.rowcount)


def db_repair_queue(cache_dir: Path) -> dict[str, int]:
    _ensure_schema(cache_dir)
    stats = {"added": 0, "reset": 0}
    now = _utc_now()
    sources_dir = cache_dir / "sources"

    with _connect(cache_dir) as conn:
        # Reset stuck processing jobs
        result = conn.execute(
            "UPDATE jobs SET status='pending', started_at=NULL, updated_at=? WHERE status='processing'",
            (now,),
        )
        stats["reset"] = int(result.rowcount)

        # Discover source dirs with results but no job
        known_source_ids = {
            row[0] for row in conn.execute("SELECT source_id FROM jobs WHERE source_id IS NOT NULL").fetchall()
        }

        if sources_dir.exists():
            for source_dir in sources_dir.iterdir():
                if not source_dir.is_dir():
                    continue
                sid = source_dir.name
                if sid in known_source_ids:
                    continue

                has_result_files = any(
                    item.is_file() and (item.name == "transcript.txt" or item.name.startswith("summary-"))
                    for item in source_dir.iterdir()
                )
                if not has_result_files:
                    continue

                meta_path = source_dir / "metadata.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, Exception):
                    continue

                source_input = str(meta.get("source", sid))
                workflow_name = str(meta.get("workflow_name") or "audio_summary")
                default_params = json.dumps(
                    {
                        "mode": "full",
                        "format": "markdown",
                        "timestamps": False,
                        "no_cache": False,
                    }
                )
                job_id = uuid.uuid4().hex[:12]
                conn.execute(
                    """INSERT OR IGNORE INTO jobs
                    (job_id, workflow_name, source, source_id, display_name, params,
                     status, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        job_id,
                        workflow_name,
                        source_input,
                        sid,
                        str(meta.get("display_name", sid)),
                        default_params,
                        "done",
                        now,
                        now,
                    ),
                )
                stats["added"] += 1

    return stats


def db_schedule_retry(cache_dir: Path, job_id: str, delay_seconds: float) -> bool:
    """Schedule a failed job for retry after delay_seconds."""
    _ensure_schema(cache_dir)
    from datetime import timedelta

    next_retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
    with _connect(cache_dir) as conn:
        existing = conn.execute("SELECT retry_count FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not existing:
            return False
        retry_count = (existing["retry_count"] or 0) + 1
        conn.execute(
            """UPDATE jobs SET status='pending', retry_count=?, next_retry_at=?,
               started_at=NULL, finished_at=NULL, updated_at=? WHERE job_id=?""",
            (retry_count, next_retry_at, _utc_now(), job_id),
        )
    return True


def db_claim_retry_jobs(cache_dir: Path) -> list[dict[str, Any]]:
    """Return jobs whose next_retry_at <= now() and status='pending'."""
    _ensure_schema(cache_dir)
    now = _utc_now()
    with _connect(cache_dir) as conn:
        rows = conn.execute(
            """SELECT * FROM jobs WHERE status='pending'
               AND next_retry_at IS NOT NULL AND next_retry_at <= ?
               ORDER BY next_retry_at""",
            (now,),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def db_move_to_dead_letter(cache_dir: Path, job_id: str) -> bool:
    """Move a job to dead_letter status (permanently failed)."""
    _ensure_schema(cache_dir)
    with _connect(cache_dir) as conn:
        existing = conn.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not existing:
            return False
        conn.execute(
            "UPDATE jobs SET status='dead_letter', updated_at=? WHERE job_id=?",
            (_utc_now(), job_id),
        )
    return True


def db_prune_jobs(
    cache_dir: Path,
    *,
    statuses: set[str] | None = None,
    source_id: str | None = None,
    stale_only: bool = False,
) -> dict[str, int]:
    _ensure_schema(cache_dir)
    valid_statuses = {"pending", "processing", "done", "failed", "dead_letter"}
    chosen_statuses = set(statuses or valid_statuses) & valid_statuses
    if not chosen_statuses:
        with _connect(cache_dir) as conn:
            remaining = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        return {"removed": 0, "remaining": remaining}

    with _connect(cache_dir) as conn:
        placeholders = ",".join("?" * len(chosen_statuses))
        if source_id:
            rows = conn.execute(
                f"SELECT job_id, source_id FROM jobs WHERE status IN ({placeholders}) AND source_id=?",
                list(chosen_statuses) + [source_id],
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT job_id, source_id FROM jobs WHERE status IN ({placeholders})",
                list(chosen_statuses),
            ).fetchall()

        to_remove = []
        for row in rows:
            if stale_only:
                sid = str(row["source_id"] or "").strip()
                if not sid:
                    continue
                if (cache_dir / "sources" / sid).exists():
                    continue
            to_remove.append(row["job_id"])

        if to_remove:
            del_placeholders = ",".join("?" * len(to_remove))
            conn.execute(f"DELETE FROM jobs WHERE job_id IN ({del_placeholders})", to_remove)

        remaining = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    return {"removed": len(to_remove), "remaining": remaining}
