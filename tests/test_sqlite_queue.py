"""Tests for the SQLite-backed queue (db.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solux.db import (
    db_claim_next_pending_job,
    db_enqueue_jobs,
    db_queue_counts,
    db_read_job,
    db_read_jobs,
    db_repair_queue,
    db_reset_processing_jobs,
    db_retry_failed_jobs,
    db_update_job,
)


def test_enqueue_and_read(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = db_enqueue_jobs(cache_dir, ["http://example.com/audio.mp3"], workflow_name="audio_summary")
    assert len(created) == 1
    job = created[0]
    assert job["status"] == "pending"
    assert job["workflow_name"] == "audio_summary"
    assert job["source"] == "http://example.com/audio.mp3"

    jobs = db_read_jobs(cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == job["job_id"]


def test_claim_next_pending_job(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["ep1.mp3", "ep2.mp3"])
    claimed = db_claim_next_pending_job(cache_dir)
    assert claimed is not None
    assert claimed["status"] == "processing"
    assert "started_at" in claimed

    # Second claim gets the second job
    claimed2 = db_claim_next_pending_job(cache_dir)
    assert claimed2 is not None
    assert claimed2["job_id"] != claimed["job_id"]

    # No more pending
    assert db_claim_next_pending_job(cache_dir) is None


def test_update_job(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = db_enqueue_jobs(cache_dir, ["ep.mp3"])
    job_id = created[0]["job_id"]

    ok = db_update_job(cache_dir, job_id, status="done", output_path="/tmp/out.md")
    assert ok is True

    jobs = db_read_jobs(cache_dir)
    assert jobs[0]["status"] == "done"
    assert jobs[0]["output_path"] == "/tmp/out.md"


def test_update_nonexistent_job(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    ok = db_update_job(cache_dir, "nonexistent", status="done")
    assert ok is False


def test_queue_counts(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["ep1.mp3", "ep2.mp3", "ep3.mp3"])
    claimed = db_claim_next_pending_job(cache_dir)
    db_update_job(cache_dir, claimed["job_id"], status="done")

    counts = db_queue_counts(cache_dir)
    assert counts["done"] == 1
    assert counts["pending"] == 2
    assert counts["processing"] == 0
    assert counts["failed"] == 0
    assert counts["dead_letter"] == 0


def test_retry_failed_jobs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["ep1.mp3", "ep2.mp3"])
    c1 = db_claim_next_pending_job(cache_dir)
    c2 = db_claim_next_pending_job(cache_dir)
    db_update_job(cache_dir, c1["job_id"], status="failed", error="some error")
    db_update_job(cache_dir, c2["job_id"], status="failed", error="another error")

    reset = db_retry_failed_jobs(cache_dir)
    assert len(reset) == 2
    for job in reset:
        assert job["status"] == "pending"
        assert "error" not in job

    counts = db_queue_counts(cache_dir)
    assert counts["pending"] == 2
    assert counts["failed"] == 0


def test_retry_specific_job_ids(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["ep1.mp3", "ep2.mp3"])
    c1 = db_claim_next_pending_job(cache_dir)
    c2 = db_claim_next_pending_job(cache_dir)
    db_update_job(cache_dir, c1["job_id"], status="failed")
    db_update_job(cache_dir, c2["job_id"], status="failed")

    reset = db_retry_failed_jobs(cache_dir, job_ids=[c1["job_id"]])
    assert len(reset) == 1
    assert reset[0]["job_id"] == c1["job_id"]


def test_retry_dead_letter_jobs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = db_enqueue_jobs(cache_dir, ["ep1.mp3"])
    db_update_job(cache_dir, created[0]["job_id"], status="dead_letter", error="terminal")

    reset = db_retry_failed_jobs(cache_dir)
    assert len(reset) == 1
    assert reset[0]["status"] == "pending"

    counts = db_queue_counts(cache_dir)
    assert counts["pending"] == 1
    assert counts["dead_letter"] == 0


def test_reset_processing_jobs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["ep1.mp3", "ep2.mp3"])
    db_claim_next_pending_job(cache_dir)  # moves to processing

    count = db_reset_processing_jobs(cache_dir)
    assert count == 1
    counts = db_queue_counts(cache_dir)
    assert counts["processing"] == 0
    assert counts["pending"] == 2


def test_repair_queue_resets_stuck(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["ep.mp3"])
    db_claim_next_pending_job(cache_dir)  # stuck processing

    stats = db_repair_queue(cache_dir)
    assert stats["reset"] == 1
    assert stats["added"] == 0
    counts = db_queue_counts(cache_dir)
    assert counts["processing"] == 0
    assert counts["pending"] == 1


def test_repair_queue_adds_synthetic_jobs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    # Create a source dir with result files and metadata
    source_id = "abc123"
    source_dir = cache_dir / "sources" / source_id
    source_dir.mkdir(parents=True)
    (source_dir / "summary-full.md").write_text("summary")
    (source_dir / "metadata.json").write_text(
        json.dumps({"source": "http://example.com", "workflow_name": "audio_summary", "display_name": "Test"})
    )

    stats = db_repair_queue(cache_dir)
    assert stats["added"] == 1

    jobs = db_read_jobs(cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["source_id"] == source_id
    assert jobs[0]["status"] == "done"


def test_migration_from_json(tmp_path: Path) -> None:
    """Test auto-migration from jobs.json to SQLite."""
    cache_dir = tmp_path / "cache"
    queue_dir = cache_dir / "queue"
    queue_dir.mkdir(parents=True)

    # Write a legacy jobs.json
    legacy_jobs = [
        {
            "job_id": "abc000000001",
            "workflow_name": "audio_summary",
            "source": "ep.mp3",
            "params": {"mode": "full", "format": "markdown", "timestamps": False, "no_cache": False},
            "status": "done",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:01:00+00:00",
        }
    ]
    (queue_dir / "jobs.json").write_text(json.dumps(legacy_jobs))

    # Reading triggers migration
    jobs = db_read_jobs(cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "abc000000001"
    assert jobs[0]["status"] == "done"

    # jobs.json should be renamed
    assert (queue_dir / "jobs.json.migrated").exists()
    assert not (queue_dir / "jobs.json").exists()


def test_read_job_by_id(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = db_enqueue_jobs(cache_dir, ["doc.pdf"], workflow_name="clinical_doc_triage")
    job_id = created[0]["job_id"]

    job = db_read_job(cache_dir, job_id)
    assert job is not None
    assert job["job_id"] == job_id
    assert job["workflow_name"] == "clinical_doc_triage"
    assert job["status"] == "pending"


def test_read_job_nonexistent(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    job = db_read_job(cache_dir, "does_not_exist")
    assert job is None
