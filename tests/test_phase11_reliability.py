"""Tests for Phase 11: Reliability — DB retry/dead-letter, step timeout, timing."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from solus.db import (
    db_claim_next_pending_job,
    db_enqueue_jobs,
    db_move_to_dead_letter,
    db_read_jobs,
    db_schedule_retry,
    db_update_job,
)
from solus.workflows.models import Context, Step, Workflow
from solus.workflows.engine import execute_workflow
from solus.workflows.registry import StepRegistry


def _make_ctx(data: dict | None = None) -> Context:
    from solus.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        SecurityConfig,
        WhisperConfig,
    )
    import tempfile

    config = Config(
        paths=PathsConfig(cache_dir=Path(tempfile.mkdtemp())),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="test", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        security=SecurityConfig(),
        config_path=Path("/tmp/test.toml"),
        config_exists=False,
    )
    return Context(
        source="test://source",
        source_id="sid-001",
        data=dict(data or {}),
        config=config,
        logger=logging.getLogger("test"),
    )


# --- DB retry schema ---


def test_db_retry_columns_exist(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["test-source"])
    job = db_read_jobs(cache_dir)[0]
    assert "retry_count" in job
    assert "max_retries" in job
    assert job["retry_count"] == 0
    assert job["max_retries"] == 3


def test_db_schedule_retry(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    jobs = db_enqueue_jobs(cache_dir, ["test-source"])
    job_id = jobs[0]["job_id"]

    # Claim and fail the job
    claimed = db_claim_next_pending_job(cache_dir)
    assert claimed is not None
    db_update_job(cache_dir, job_id, status="failed", error="test error")

    # Schedule retry with 60s delay
    ok = db_schedule_retry(cache_dir, job_id, delay_seconds=60)
    assert ok is True

    # Job should now be pending again with next_retry_at in the future
    jobs_after = db_read_jobs(cache_dir)
    job = jobs_after[0]
    assert job["status"] == "pending"
    assert job.get("next_retry_at") is not None
    # retry_count should be incremented
    assert job.get("retry_count", 0) == 1


def test_db_schedule_retry_not_immediately_claimed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["test-source"])
    job_id = db_claim_next_pending_job(cache_dir)["job_id"]
    db_update_job(cache_dir, job_id, status="failed")
    db_schedule_retry(cache_dir, job_id, delay_seconds=3600)  # 1 hour delay

    # Should NOT be immediately claimable (future next_retry_at)
    next_job = db_claim_next_pending_job(cache_dir)
    assert next_job is None


def test_db_schedule_retry_nonexistent_job(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["test-source"])  # Ensure schema is created
    ok = db_schedule_retry(cache_dir, "nonexistent-job-id", delay_seconds=30)
    assert ok is False


def test_db_move_to_dead_letter(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    jobs = db_enqueue_jobs(cache_dir, ["test-source"])
    job_id = jobs[0]["job_id"]

    ok = db_move_to_dead_letter(cache_dir, job_id)
    assert ok is True

    jobs_after = db_read_jobs(cache_dir)
    assert jobs_after[0]["status"] == "dead_letter"


def test_db_move_to_dead_letter_nonexistent(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    db_enqueue_jobs(cache_dir, ["test-source"])
    ok = db_move_to_dead_letter(cache_dir, "no-such-job")
    assert ok is False


def test_db_claim_retry_jobs(tmp_path: Path) -> None:
    from solus.db import db_claim_retry_jobs

    cache_dir = tmp_path / "cache"
    jobs = db_enqueue_jobs(cache_dir, ["test-source"])
    job_id = jobs[0]["job_id"]

    # Claim and fail
    db_claim_next_pending_job(cache_dir)
    db_update_job(cache_dir, job_id, status="failed")
    # Schedule retry in the past (already due)
    db_schedule_retry(cache_dir, job_id, delay_seconds=-1)

    # Should appear in retry jobs
    retry_jobs = db_claim_retry_jobs(cache_dir)
    assert any(j["job_id"] == job_id for j in retry_jobs)


def test_db_retry_count_increments(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    jobs = db_enqueue_jobs(cache_dir, ["test-source"])
    job_id = jobs[0]["job_id"]
    db_claim_next_pending_job(cache_dir)

    db_update_job(cache_dir, job_id, status="failed")
    db_schedule_retry(cache_dir, job_id, delay_seconds=-1)

    jobs2 = db_read_jobs(cache_dir)
    assert jobs2[0].get("retry_count", 0) == 1

    # Claim again and retry again
    db_claim_next_pending_job(cache_dir)
    db_update_job(cache_dir, job_id, status="failed")
    db_schedule_retry(cache_dir, job_id, delay_seconds=-1)

    jobs3 = db_read_jobs(cache_dir)
    assert jobs3[0].get("retry_count", 0) == 2


# --- Step model timeout_seconds ---


def test_step_timeout_seconds_field() -> None:
    step = Step(name="test", type="ai.llm_prompt", timeout_seconds=30)
    assert step.timeout_seconds == 30


def test_step_timeout_seconds_default_none() -> None:
    step = Step(name="test", type="ai.llm_prompt")
    assert step.timeout_seconds is None


# --- Engine step timing ---


def test_engine_records_step_timings() -> None:
    ctx = _make_ctx()
    reg = StepRegistry()

    def quick_handler(c: Context, s: Step) -> Context:
        c.data["done"] = True
        return c

    reg.register("test.quick", quick_handler)
    workflow = Workflow(
        name="timing_test",
        description="",
        steps=[Step(name="step1", type="test.quick")],
    )
    result = execute_workflow(workflow, ctx, reg)
    timings = result.data.get("_step_timings", [])
    assert len(timings) == 1
    assert timings[0]["name"] == "step1"
    assert timings[0]["type"] == "test.quick"
    assert "duration_ms" in timings[0]
    assert timings[0]["duration_ms"] >= 0


def test_engine_multiple_step_timings() -> None:
    ctx = _make_ctx()
    reg = StepRegistry()

    def h1(c: Context, s: Step) -> Context:
        c.data["a"] = 1
        return c

    def h2(c: Context, s: Step) -> Context:
        c.data["b"] = 2
        return c

    reg.register("test.h1", h1)
    reg.register("test.h2", h2)
    workflow = Workflow(
        name="multi_timing",
        description="",
        steps=[
            Step(name="step-a", type="test.h1"),
            Step(name="step-b", type="test.h2"),
        ],
    )
    result = execute_workflow(workflow, ctx, reg)
    timings = result.data.get("_step_timings", [])
    assert len(timings) == 2
    assert timings[0]["name"] == "step-a"
    assert timings[1]["name"] == "step-b"


# --- Engine step timeout ---


def test_engine_step_timeout_raises() -> None:
    ctx = _make_ctx()
    reg = StepRegistry()

    def slow_handler(c: Context, s: Step) -> Context:
        time.sleep(5)
        return c

    reg.register("test.slow", slow_handler)
    workflow = Workflow(
        name="timeout_test",
        description="",
        steps=[Step(name="slow", type="test.slow", timeout_seconds=1)],
    )
    with pytest.raises(RuntimeError, match="timed out"):
        execute_workflow(workflow, ctx, reg)


def test_engine_step_timeout_returns_promptly() -> None:
    ctx = _make_ctx()
    reg = StepRegistry()

    def slow_handler(c: Context, s: Step) -> Context:
        time.sleep(2)
        return c

    reg.register("test.slow", slow_handler)
    workflow = Workflow(
        name="timeout_prompt",
        description="",
        steps=[Step(name="slow", type="test.slow", timeout_seconds=1)],
    )
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        execute_workflow(workflow, ctx, reg)
    elapsed = time.monotonic() - start
    assert elapsed < 1.8


def test_engine_foreach_timeout_raises() -> None:
    ctx = _make_ctx({"items": list(range(5))})
    reg = StepRegistry()

    def slow_handler(c: Context, s: Step) -> Context:
        time.sleep(0.5)
        return c

    reg.register("test.slow", slow_handler)
    workflow = Workflow(
        name="foreach_timeout_test",
        description="",
        steps=[Step(name="slow_foreach", type="test.slow", foreach="items", timeout_seconds=1)],
    )
    with pytest.raises(RuntimeError, match="timed out"):
        execute_workflow(workflow, ctx, reg)


def test_engine_step_no_timeout_completes() -> None:
    ctx = _make_ctx()
    reg = StepRegistry()

    def fast_handler(c: Context, s: Step) -> Context:
        c.data["done"] = True
        return c

    reg.register("test.fast", fast_handler)
    workflow = Workflow(
        name="fast_test",
        description="",
        steps=[Step(name="fast", type="test.fast", timeout_seconds=None)],
    )
    result = execute_workflow(workflow, ctx, reg)
    assert result.data.get("done") is True


def test_step_timeout_daemon_thread_returns_result() -> None:
    """Verify that the daemon-thread timeout wrapper returns correct results."""
    from solus.workflows.engine import _run_step_with_optional_timeout

    result = _run_step_with_optional_timeout(
        lambda: "ok",
        step_name="x",
        step_type="test.handler",
        timeout_seconds=5,
    )
    assert result == "ok"


# --- Worker retry logic integration ---


def test_worker_retry_logic(tmp_path: Path) -> None:
    from solus.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        SecurityConfig,
        WhisperConfig,
    )
    from solus.queueing import enqueue_jobs, read_jobs
    from solus.worker import run_log_worker

    cache_dir = tmp_path / "cache"
    config = Config(
        paths=PathsConfig(cache_dir=cache_dir),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="test", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        security=SecurityConfig(),
        config_path=Path("/tmp/test.toml"),
        config_exists=False,
    )
    enqueue_jobs(cache_dir, ["fail-source"])

    with patch("solus.worker.execute_source_workflow", side_effect=RuntimeError("test fail")):
        run_log_worker(config, poll_interval=0.01, once=True)

    jobs = read_jobs(cache_dir)
    assert jobs[0]["status"] in {"pending", "dead_letter"}
    assert "error" in jobs[0]
    # retry_count should be non-zero or job went to dead_letter
    if jobs[0]["status"] == "pending":
        assert jobs[0].get("retry_count", 0) > 0


def test_worker_dead_letter_after_max_retries(tmp_path: Path) -> None:
    """After max retries + 1 failures, job should be dead_letter."""
    from solus.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        SecurityConfig,
        WhisperConfig,
    )
    from solus.db import db_enqueue_jobs, db_read_jobs, db_schedule_retry, db_update_job
    from solus.db import db_claim_next_pending_job, db_move_to_dead_letter

    cache_dir = tmp_path / "cache"
    jobs = db_enqueue_jobs(cache_dir, ["dead-source"])
    job_id = jobs[0]["job_id"]

    # Simulate 4 failures (retry_count goes 0→1→2→3→dead)
    for i in range(3):
        db_claim_next_pending_job(cache_dir)
        db_update_job(cache_dir, job_id, status="failed", error=f"fail {i}")
        db_schedule_retry(cache_dir, job_id, delay_seconds=-1)

    # 4th failure → dead_letter
    db_claim_next_pending_job(cache_dir)
    db_update_job(cache_dir, job_id, status="failed", error="final fail")
    db_move_to_dead_letter(cache_dir, job_id)

    final_job = db_read_jobs(cache_dir)[0]
    assert final_job["status"] == "dead_letter"


def test_worker_timeout_error_skips_retry_and_moves_to_dead_letter(tmp_path: Path) -> None:
    from solus.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        SecurityConfig,
        WhisperConfig,
    )
    from solus.queueing import enqueue_jobs, read_jobs
    from solus.worker import run_log_worker
    from solus.workflows.engine import StepTimeoutError

    cache_dir = tmp_path / "cache"
    config = Config(
        paths=PathsConfig(cache_dir=cache_dir),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="test", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        security=SecurityConfig(),
        config_path=Path("/tmp/test.toml"),
        config_exists=False,
    )
    enqueue_jobs(cache_dir, ["timeout-source"])

    with patch("solus.worker.execute_source_workflow", side_effect=StepTimeoutError("timed out")):
        run_log_worker(config, poll_interval=0.01, once=True)

    jobs = read_jobs(cache_dir)
    assert jobs[0]["status"] == "dead_letter"
    assert jobs[0].get("retry_count", 0) == 0
