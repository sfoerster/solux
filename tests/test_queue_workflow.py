from __future__ import annotations

import dataclasses
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from solux import paths
from solux.background import start_background_worker
from solux.cleanup import run_cleanup
from solux.config import BinaryConfig, Config, OllamaConfig, PathsConfig, PromptsConfig, WhisperConfig
from solux.pipeline import process_source
from solux.queueing import (
    claim_next_pending_job,
    clear_worker_pid,
    current_worker_pid,
    enqueue_jobs,
    prune_jobs,
    queue_counts,
    read_worker_pid,
    read_jobs,
    repair_queue,
    reset_processing_jobs,
    retry_failed_jobs,
    update_job,
    worker_pid_path,
    write_worker_pid,
    worker_log_path,
)
from solux.serve import FileEntry, _render_file_content, discover_sources
from solux.worker import run_log_worker


def _make_config(cache_dir: Path) -> Config:
    return Config(
        paths=PathsConfig(cache_dir=cache_dir),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=2),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="qwen3:8b", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        config_path=cache_dir / "config.toml",
        config_exists=True,
    )


def test_queue_lifecycle(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["a.mp3", "b.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    assert len(created) == 2
    counts = queue_counts(cache_dir)
    assert counts == {"pending": 2, "processing": 0, "done": 0, "failed": 0, "dead_letter": 0}

    claimed = claim_next_pending_job(cache_dir)
    assert claimed is not None
    assert claimed["status"] == "processing"
    counts = queue_counts(cache_dir)
    assert counts == {"pending": 1, "processing": 1, "done": 0, "failed": 0, "dead_letter": 0}


def test_worker_marks_job_done_and_logs_queue_length(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    created = enqueue_jobs(
        cache_dir,
        sources=["episode-a.mp3"],
        mode="tldr",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    job_id = created[0]["job_id"]

    def fake_execute_source_workflow(
        config,
        *,
        source,
        workflow_name,
        params,
        no_cache,
        verbose,
        progress,
        on_step_complete=None,
    ):
        source_id = paths.compute_source_id(source)
        mode = str(params.get("mode", "full"))
        output_format = str(params.get("format", "markdown"))
        export_output = paths.exported_output_path(
            config.paths.cache_dir,
            source_id,
            display_slug="episode-a",
            mode=mode,
            output_format=output_format,
        )
        export_output.write_text("summary", encoding="utf-8")
        progress("fake processing step")
        return SimpleNamespace(
            source_id=source_id,
            data={
                "display_name": "episode-a.mp3",
                "export_output_path": str(export_output),
            },
        )

    monkeypatch.setattr("solux.worker.execute_source_workflow", fake_execute_source_workflow)
    rc = run_log_worker(config, poll_interval=0.01, once=True)
    assert rc == 0

    jobs = read_jobs(cache_dir)
    assert jobs[0]["job_id"] == job_id
    assert jobs[0]["status"] == "done"
    text = worker_log_path(cache_dir).read_text(encoding="utf-8")
    assert "Queue length:" in text
    assert "Queue length after completion:" in text


def test_worker_marks_job_failed(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    enqueue_jobs(
        cache_dir,
        sources=["episode-fail.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )

    def fake_execute_source_workflow(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("solux.worker.execute_source_workflow", fake_execute_source_workflow)
    rc = run_log_worker(config, poll_interval=0.01, once=True)
    assert rc == 0

    jobs = read_jobs(cache_dir)
    # With retry logic, first failure schedules retry → status becomes 'pending'
    # After max retries exhausted it becomes 'dead_letter'. Either indicates failure was recorded.
    assert jobs[0]["status"] in {"failed", "pending", "dead_letter"}
    assert "error" in jobs[0]
    text = worker_log_path(cache_dir).read_text(encoding="utf-8")
    assert "Queue length after failure:" in text


def test_worker_uses_configured_trigger_dir_and_reloads_triggers(tmp_path: Path, monkeypatch) -> None:
    from solux.config import SecurityConfig
    from solux.triggers.spec import Trigger

    cache_dir = tmp_path / "cache"
    trigger_dir = tmp_path / "custom-triggers.d"
    config = Config(
        paths=PathsConfig(cache_dir=cache_dir),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=2),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="qwen3:8b", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        security=SecurityConfig(),
        config_path=cache_dir / "config.toml",
        config_exists=True,
        workflows_dir=tmp_path / "workflows.d",
        modules_dir=tmp_path / "modules.d",
        triggers_dir=trigger_dir,
    )

    seen_trigger_dirs: list[Path | None] = []
    run_trigger_calls: list[int] = []
    trigger = Trigger(name="t", type="cron", workflow="audio_summary", params={}, config={"interval_seconds": 60})

    def _fake_load_triggers(triggers_dir=None):
        seen_trigger_dirs.append(triggers_dir)
        return [trigger], []

    def _fake_run_triggers(_cache_dir, _triggers, *, stop_event, state_db_path=None, config=None):
        del _cache_dir, _triggers, stop_event, state_db_path, config
        run_trigger_calls.append(1)
        return []

    class _FakeHotReloader:
        def __init__(
            self,
            modules_dir=None,
            workflows_dir=None,
            triggers_dir=None,
            interval=5.0,
            on_reload=None,
        ) -> None:
            self._on_reload = on_reload

        def start(self) -> None:
            if self._on_reload is not None:
                self._on_reload()

        def stop(self) -> None:
            return

    monkeypatch.setattr("solux.worker.load_triggers", _fake_load_triggers)
    monkeypatch.setattr("solux.worker.run_triggers", _fake_run_triggers)
    monkeypatch.setattr("solux.worker.HotReloader", _FakeHotReloader)

    rc = run_log_worker(config, poll_interval=0.01, once=True)
    assert rc == 0
    assert seen_trigger_dirs and all(path == trigger_dir for path in seen_trigger_dirs)
    # initial trigger start + one reload callback from hot reloader.start()
    assert len(run_trigger_calls) == 2


def test_cleanup_artifacts_only_keeps_finished_outputs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    source_dir = paths.source_dir(cache_dir, "abc123")
    (source_dir / "audio.mp3").write_text("raw", encoding="utf-8")
    (source_dir / "audio.wav").write_text("wav", encoding="utf-8")
    (source_dir / "transcript.txt").write_text("transcript", encoding="utf-8")
    (source_dir / "summary-full.md").write_text("summary", encoding="utf-8")
    (source_dir / "metadata.json").write_text("{}", encoding="utf-8")

    export = paths.exported_output_path(
        cache_dir,
        source_id="abc123",
        display_slug="episode",
        mode="full",
        output_format="markdown",
    )
    export.write_text("summary", encoding="utf-8")

    rc = run_cleanup(config, artifacts_only=True, yes=True)
    assert rc == 0
    assert not (source_dir / "audio.mp3").exists()
    assert not (source_dir / "audio.wav").exists()
    assert (source_dir / "transcript.txt").exists()
    assert (source_dir / "summary-full.md").exists()
    assert (source_dir / "metadata.json").exists()
    assert export.exists()


def test_cleanup_finished_only_with_age_filter(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)

    old_source = paths.source_dir(cache_dir, "old111")
    (old_source / "summary-full.md").write_text("old", encoding="utf-8")
    (old_source / "transcript.txt").write_text("old", encoding="utf-8")
    (old_source / "metadata.json").write_text("{}", encoding="utf-8")
    old_export = paths.exported_output_path(cache_dir, "old111", "old-episode", "full", "markdown")
    old_export.write_text("old", encoding="utf-8")

    new_source = paths.source_dir(cache_dir, "new222")
    (new_source / "summary-full.md").write_text("new", encoding="utf-8")
    (new_source / "transcript.txt").write_text("new", encoding="utf-8")
    (new_source / "metadata.json").write_text("{}", encoding="utf-8")
    new_export = paths.exported_output_path(cache_dir, "new222", "new-episode", "full", "markdown")
    new_export.write_text("new", encoding="utf-8")

    old_time = time.time() - (20 * 86400)
    for p in [old_source / "summary-full.md", old_source / "transcript.txt", old_source / "metadata.json", old_export]:
        os.utime(p, (old_time, old_time))

    rc = run_cleanup(config, finished_only=True, older_than_days=7, yes=True)
    assert rc == 0
    assert not old_source.exists()
    assert not old_export.exists()
    assert new_source.exists()
    assert new_export.exists()


def test_process_source_exports_slugged_output_name(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    source = str((tmp_path / "My Episode 01.mp3").resolve())
    Path(source).write_text("audio", encoding="utf-8")

    def fake_execute_source_workflow(
        config,
        *,
        source,
        workflow_name,
        params,
        no_cache,
        verbose,
        progress,
        on_step_complete=None,
    ):
        source_id = paths.compute_source_id(source)
        mode = str(params.get("mode", "full"))
        output_format = str(params.get("format", "markdown"))
        source_dir = paths.source_dir(config.paths.cache_dir, source_id)
        wav = paths.normalized_wav_path(config.paths.cache_dir, source_id)
        wav.write_text("wav", encoding="utf-8")
        transcript = paths.transcript_path(config.paths.cache_dir, source_id)
        transcript.write_text("hello world", encoding="utf-8")
        cache_output = paths.summary_path(config.paths.cache_dir, source_id, mode, output_format)
        cache_output.write_text("summary content", encoding="utf-8")
        export_output = paths.exported_output_path(
            config.paths.cache_dir,
            source_id=source_id,
            display_slug="my-episode-01.mp3",
            mode=mode,
            output_format=output_format,
        )
        export_output.write_text("summary content", encoding="utf-8")
        paths.metadata_path(config.paths.cache_dir, source_id).write_text(
            json.dumps({"display_name": "My Episode 01.mp3", "source": source}),
            encoding="utf-8",
        )
        return SimpleNamespace(
            source_id=source_id,
            data={
                "display_name": "My Episode 01.mp3",
                "audio_input_path": str(source_dir / "audio.mp3"),
                "wav_path": str(wav),
                "transcript_path": str(transcript),
                "cache_output_path": str(cache_output),
                "export_output_path": str(export_output),
                "output_text": "summary content",
            },
        )

    monkeypatch.setattr("solux.pipeline.execute_source_workflow", fake_execute_source_workflow)

    result = process_source(
        config,
        source=source,
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
        verbose=False,
    )
    assert result.export_output_path.exists()
    assert result.export_output_path.name.endswith("-full.md")
    assert "my-episode-01.mp3" in result.export_output_path.name
    metadata = json.loads(paths.metadata_path(cache_dir, result.source_id).read_text(encoding="utf-8"))
    assert metadata["display_name"] == "My Episode 01.mp3"


def test_discover_sources_includes_only_processed_outputs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    src_a = paths.source_dir(cache_dir, "aaa111")
    (src_a / "summary-full.md").write_text("summary", encoding="utf-8")
    (src_a / "metadata.json").write_text(
        json.dumps({"display_name": "Episode A", "source": "episode-a.mp3"}),
        encoding="utf-8",
    )

    src_b = paths.source_dir(cache_dir, "bbb222")
    (src_b / "audio.wav").write_text("audio", encoding="utf-8")
    (src_b / "metadata.json").write_text(
        json.dumps({"display_name": "Episode B", "source": "episode-b.mp3"}),
        encoding="utf-8",
    )

    discovered = discover_sources(cache_dir)
    assert len(discovered) == 1
    assert discovered[0].source_id == "aaa111"
    assert discovered[0].title == "Episode A"
    assert discovered[0].files[0].name == "summary-full.md"


def test_discover_sources_fallback_title_for_watch_url(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    source_dir = paths.source_dir(cache_dir, "ddd333")
    (source_dir / "summary-full.md").write_text("# Title\n\n- bullet", encoding="utf-8")
    (source_dir / "metadata.json").write_text(
        json.dumps(
            {
                "display_name": "watch",
                "source": "https://www.youtube.com/watch?v=abc123xyz",
            }
        ),
        encoding="utf-8",
    )

    discovered = discover_sources(cache_dir)
    assert len(discovered) == 1
    assert discovered[0].title == "YouTube abc123xyz"


def test_discover_sources_prefers_info_json_title_and_backfills_metadata(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    source_dir = paths.source_dir(cache_dir, "eee444")
    (source_dir / "summary-full.md").write_text("# Summary", encoding="utf-8")
    (source_dir / "audio.info.json").write_text(
        json.dumps({"title": "Actual Movie Title"}),
        encoding="utf-8",
    )
    meta_path = source_dir / "metadata.json"
    meta_path.write_text(
        json.dumps(
            {
                "display_name": "YouTube abc123",
                "source": "https://www.youtube.com/watch?v=abc123",
            }
        ),
        encoding="utf-8",
    )

    discovered = discover_sources(cache_dir)
    assert len(discovered) == 1
    assert discovered[0].title == "Actual Movie Title"

    persisted = json.loads(meta_path.read_text(encoding="utf-8"))
    assert persisted["display_name"] == "Actual Movie Title"


def test_render_file_content_renders_markdown(tmp_path: Path) -> None:
    md_path = tmp_path / "summary-full.md"
    md_path.write_text("## TL;DR\n\n- **One**\n- `code`", encoding="utf-8")
    stat = md_path.stat()
    entry = FileEntry(name=md_path.name, path=md_path, size_bytes=stat.st_size, mtime=stat.st_mtime)
    rendered = _render_file_content(entry)
    assert "<article class='markdown'>" in rendered
    assert "<h2>TL;DR</h2>" in rendered
    assert "<strong>One</strong>" in rendered


# ── New tests for weaknesses 2, 3, 5, 7 ──────────────────────────────────────


def test_retry_failed_jobs_resets_all(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["fail-a.mp3", "fail-b.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    for job in created:
        update_job(cache_dir, job["job_id"], status="failed", error="boom", finished_at="2026-01-01T00:00:00+00:00")

    counts = queue_counts(cache_dir)
    assert counts["failed"] == 2

    reset = retry_failed_jobs(cache_dir)
    assert len(reset) == 2
    for job in reset:
        assert job["status"] == "pending"
        assert "error" not in job
        assert "finished_at" not in job

    counts = queue_counts(cache_dir)
    assert counts["failed"] == 0
    assert counts["pending"] == 2


def test_retry_failed_jobs_with_job_id_filter(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["a.mp3", "b.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    job_id_a = created[0]["job_id"]
    job_id_b = created[1]["job_id"]
    for j in created:
        update_job(cache_dir, j["job_id"], status="failed", error="boom")

    reset = retry_failed_jobs(cache_dir, job_ids=[job_id_a])
    assert len(reset) == 1
    assert reset[0]["job_id"] == job_id_a

    jobs = {j["job_id"]: j for j in read_jobs(cache_dir)}
    assert jobs[job_id_a]["status"] == "pending"
    assert jobs[job_id_b]["status"] == "failed"


def test_retry_failed_jobs_includes_dead_letter(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["a.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    job_id = created[0]["job_id"]
    update_job(cache_dir, job_id, status="dead_letter", error="terminal")

    counts = queue_counts(cache_dir)
    assert counts["dead_letter"] == 1

    reset = retry_failed_jobs(cache_dir)
    assert len(reset) == 1
    assert reset[0]["job_id"] == job_id
    assert reset[0]["status"] == "pending"

    counts = queue_counts(cache_dir)
    assert counts["dead_letter"] == 0
    assert counts["pending"] == 1


def test_repair_queue_adds_synthetic_done_jobs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    # Create a source dir with results + metadata but no queue entry
    from solux import paths as _paths

    source_dir = _paths.source_dir(cache_dir, "aaa111")
    (source_dir / "summary-full.md").write_text("summary", encoding="utf-8")
    (source_dir / "metadata.json").write_text(
        json.dumps({"source": "episode-a.mp3", "display_name": "Episode A"}),
        encoding="utf-8",
    )

    stats = repair_queue(cache_dir)
    assert stats["added"] == 1
    assert stats["reset"] == 0

    jobs = read_jobs(cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "done"
    assert jobs[0]["source_id"] == "aaa111"


def test_repair_queue_skips_metadata_only_source(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    from solux import paths as _paths

    source_dir = _paths.source_dir(cache_dir, "metaonly")
    (source_dir / "metadata.json").write_text(
        json.dumps({"source": "episode-metaonly.mp3", "display_name": "MetaOnly"}),
        encoding="utf-8",
    )

    stats = repair_queue(cache_dir)
    assert stats["added"] == 0
    assert stats["reset"] == 0
    assert read_jobs(cache_dir) == []


def test_repair_queue_resets_stuck_processing_jobs(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["stuck.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    # Manually set to processing (simulating a stuck worker)
    update_job(cache_dir, created[0]["job_id"], status="processing")

    stats = repair_queue(cache_dir)
    assert stats["reset"] == 1

    jobs = read_jobs(cache_dir)
    assert jobs[0]["status"] == "pending"


def test_worker_pid_roundtrip_and_current_pid(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    write_worker_pid(cache_dir, os.getpid())
    assert read_worker_pid(cache_dir) == os.getpid()
    assert current_worker_pid(cache_dir) == os.getpid()
    clear_worker_pid(cache_dir)
    assert read_worker_pid(cache_dir) is None


def test_current_worker_pid_clears_stale_pid_file(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    stale_pid = os.getpid() + 10_000_000
    write_worker_pid(cache_dir, stale_pid)
    assert current_worker_pid(cache_dir) is None
    assert not worker_pid_path(cache_dir).exists()


def test_start_background_worker_detects_immediate_start_failure(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"

    class _DeadProc:
        pid = 424242

        @staticmethod
        def poll() -> int:
            return 1

    monkeypatch.setattr("solux.background.subprocess.Popen", lambda *args, **kwargs: _DeadProc())
    monkeypatch.setattr("solux.background.time.sleep", lambda *_args, **_kwargs: None)

    started, pid, reason = start_background_worker(cache_dir, poll_interval=1.0, workers=1)
    assert started is False
    assert pid is None
    assert reason == "start-failed"
    assert read_worker_pid(cache_dir) is None


def test_prune_jobs_default_done_failed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["a.mp3", "b.mp3", "c.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    update_job(cache_dir, created[0]["job_id"], status="done")
    update_job(cache_dir, created[1]["job_id"], status="failed")
    update_job(cache_dir, created[2]["job_id"], status="pending")

    stats = prune_jobs(cache_dir, statuses={"done", "failed"})
    assert stats["removed"] == 2
    assert stats["remaining"] == 1
    counts = queue_counts(cache_dir)
    assert counts["pending"] == 1
    assert counts["done"] == 0
    assert counts["failed"] == 0


def test_prune_jobs_stale_only(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["a.mp3", "b.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    update_job(cache_dir, created[0]["job_id"], status="done", source_id="live111")
    update_job(cache_dir, created[1]["job_id"], status="done", source_id="stale222")
    paths.source_dir(cache_dir, "live111")

    stats = prune_jobs(cache_dir, statuses={"done"}, stale_only=True)
    assert stats["removed"] == 1
    jobs = read_jobs(cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["source_id"] == "live111"


def test_reset_processing_jobs_helper(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["stuck2.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    update_job(cache_dir, created[0]["job_id"], status="processing")
    reset_count = reset_processing_jobs(cache_dir)
    assert reset_count == 1
    jobs = read_jobs(cache_dir)
    assert jobs[0]["status"] == "pending"


def test_run_repair_command_fails_if_worker_running(tmp_path: Path, monkeypatch, capsys) -> None:
    from solux.cli import run_repair_command

    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)

    monkeypatch.setattr("solux.cli.maintenance.load_config", lambda: config)

    @contextmanager
    def _locked(_cache_dir):
        yield False

    monkeypatch.setattr("solux.cli.maintenance.try_worker_lock", _locked)

    rc = run_repair_command()
    captured = capsys.readouterr()
    assert rc == 1
    assert "Cannot repair queue while background worker is running" in captured.out


def test_enqueue_jobs_stores_model(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    created = enqueue_jobs(
        cache_dir,
        sources=["ep.mp3"],
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
        model="llama3:8b",
    )
    assert created[0]["model"] == "llama3:8b"


def test_worker_passes_model_to_execute_source_workflow(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    trigger_dir = tmp_path / "empty-triggers"
    trigger_dir.mkdir()
    config = dataclasses.replace(config, triggers_dir=trigger_dir)
    enqueue_jobs(
        cache_dir,
        sources=["ep-model.mp3"],
        mode="tldr",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
        model="custom:7b",
    )

    used_model: list[str | None] = []

    def fake_execute_source_workflow(
        config,
        *,
        source,
        workflow_name,
        params,
        no_cache,
        verbose,
        progress,
        on_step_complete=None,
    ):
        used_model.append(params.get("model"))
        source_id = paths.compute_source_id(source)
        mode = str(params.get("mode", "full"))
        output_format = str(params.get("format", "markdown"))
        export_output = paths.exported_output_path(
            config.paths.cache_dir, source_id, display_slug="ep-model", mode=mode, output_format=output_format
        )
        export_output.write_text("summary", encoding="utf-8")
        return SimpleNamespace(
            source_id=source_id,
            data={
                "display_name": "ep-model.mp3",
                "export_output_path": str(export_output),
            },
        )

    monkeypatch.setattr("solux.worker.execute_source_workflow", fake_execute_source_workflow)
    rc = run_log_worker(config, poll_interval=0.01, once=True)
    assert rc == 0
    assert used_model == ["custom:7b"]


def test_worker_recovers_stuck_processing_on_startup(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    created = enqueue_jobs(
        cache_dir,
        sources=["recover-me.mp3"],
        mode="tldr",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )
    update_job(cache_dir, created[0]["job_id"], status="processing")

    def fake_execute_source_workflow(
        config,
        *,
        source,
        workflow_name,
        params,
        no_cache,
        verbose,
        progress,
        on_step_complete=None,
    ):
        source_id = paths.compute_source_id(source)
        mode = str(params.get("mode", "full"))
        output_format = str(params.get("format", "markdown"))
        export_output = paths.exported_output_path(
            config.paths.cache_dir, source_id, display_slug="recover-me", mode=mode, output_format=output_format
        )
        export_output.write_text("summary", encoding="utf-8")
        return SimpleNamespace(
            source_id=source_id,
            data={
                "display_name": "recover-me.mp3",
                "export_output_path": str(export_output),
            },
        )

    monkeypatch.setattr("solux.worker.execute_source_workflow", fake_execute_source_workflow)
    rc = run_log_worker(config, poll_interval=0.01, once=True)
    assert rc == 0
    jobs = read_jobs(cache_dir)
    assert jobs[0]["status"] == "done"
    text = worker_log_path(cache_dir).read_text(encoding="utf-8")
    assert "Recovered 1 stuck processing job(s): reset to pending." in text


def test_split_into_chunks_basic() -> None:
    from solux.summarize import _split_into_chunks

    text = "Hello world. " * 50  # 650 chars
    chunks = _split_into_chunks(text, max_chars=200, overlap=50)
    assert len(chunks) > 1
    # Each chunk must not exceed max_chars
    for chunk in chunks:
        assert len(chunk) <= 200
    # All text content is covered
    assert "Hello world" in chunks[0]


def test_split_into_chunks_short_text() -> None:
    from solux.summarize import _split_into_chunks

    text = "Short."
    chunks = _split_into_chunks(text, max_chars=1000)
    assert chunks == [text]


def test_summarize_transcript_chunked_path(tmp_path: Path, monkeypatch) -> None:
    """When max_transcript_chars is set and text exceeds it, chunked path fires."""
    from solux.summarize import summarize_transcript

    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)

    # Create config with a max_transcript_chars smaller than the long transcript
    config_with_limit = Config(
        paths=config.paths,
        whisper=config.whisper,
        ollama=OllamaConfig(
            base_url=config.ollama.base_url,
            model=config.ollama.model,
            max_transcript_chars=500,
        ),
        yt_dlp=config.yt_dlp,
        ffmpeg=config.ffmpeg,
        prompts=config.prompts,
        config_path=config.config_path,
        config_exists=config.config_exists,
    )

    calls: list[str] = []

    def fake_call_ollama(cfg, prompt, model=None):
        calls.append(prompt["user"][:30])
        return "chunk summary"

    monkeypatch.setattr("solux.summarize.call_ollama_chat", fake_call_ollama)

    # ~1100 chars, well over max_transcript_chars=500
    long_transcript = "This is sentence one. " * 50
    result = summarize_transcript(
        config_with_limit,
        long_transcript,
        mode="tldr",
        output_format="markdown",
    )
    # Should have called ollama multiple times (once per chunk + final meta-summary)
    assert len(calls) >= 2
    assert result == "chunk summary"


def test_run_ingest_command_starts_background_worker(tmp_path: Path, monkeypatch, capsys) -> None:
    from solux.cli import parse_args, run_ingest_command

    config = _make_config(tmp_path / "cache")
    monkeypatch.setattr("solux.cli.queue.load_config", lambda: config)
    monkeypatch.setattr(
        "solux.cli.queue.enqueue_jobs",
        lambda *args, **kwargs: [{"job_id": "job123", "workflow_name": "audio_summary", "source": "ep.mp3"}],
    )
    monkeypatch.setattr(
        "solux.cli.queue.queue_counts",
        lambda *_args, **_kwargs: {"pending": 1, "processing": 0, "done": 0, "failed": 0, "dead_letter": 0},
    )
    monkeypatch.setattr("solux.cli.queue.ensure_background_worker", lambda *_args, **_kwargs: True)

    args = parse_args(["ingest", "ep.mp3"])
    rc = run_ingest_command(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Queued 1 job(s)." in out
    assert "Started background worker." in out


def test_run_log_command_uses_log_viewer(tmp_path: Path, monkeypatch) -> None:
    from solux.cli import parse_args, run_log_command

    config = _make_config(tmp_path / "cache")
    monkeypatch.setattr("solux.cli.queue.load_config", lambda: config)
    called: list[float] = []

    def fake_viewer(cfg, *, poll_interval, show_existing):
        assert cfg is config
        called.append(poll_interval)
        assert show_existing is True
        return 0

    monkeypatch.setattr("solux.cli.queue.run_log_viewer", fake_viewer)
    args = parse_args(["log", "--poll-interval", "1.5"])
    rc = run_log_command(args)
    assert rc == 0
    assert called == [1.5]


# ── Tests for context persistence and discovery ──────────────────────────────


def test_worker_persists_context_json(tmp_path: Path, monkeypatch) -> None:
    """After a successful job, the worker writes ctx.data as context.json in the source dir."""
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    enqueue_jobs(
        cache_dir,
        sources=["doc.pdf"],
        workflow_name="clinical_doc_triage",
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )

    def fake_execute_source_workflow(
        config,
        *,
        source,
        workflow_name,
        params,
        no_cache,
        verbose,
        progress,
        on_step_complete=None,
    ):
        source_id = paths.compute_source_id(source)
        return SimpleNamespace(
            source_id=source_id,
            data={
                "display_name": "doc.pdf",
                "doc_type": "discharge_summary",
                "urgency": "routine",
                "summary": "Patient was admitted for...",
                "entities": {"diagnoses": ["hypertension"], "medications": ["lisinopril"]},
                "export_output_path": "",
                "_internal_key": "should be skipped",
                "runtime": "should be skipped",
            },
        )

    monkeypatch.setattr("solux.worker.execute_source_workflow", fake_execute_source_workflow)
    rc = run_log_worker(config, poll_interval=0.01, once=True)
    assert rc == 0

    # Find the source dir and verify context.json was written
    source_id = paths.compute_source_id("doc.pdf")
    ctx_path = paths.source_dir(cache_dir, source_id) / "context.json"
    assert ctx_path.exists()

    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    assert ctx["doc_type"] == "discharge_summary"
    assert ctx["urgency"] == "routine"
    assert ctx["summary"] == "Patient was admitted for..."
    assert ctx["entities"]["diagnoses"] == ["hypertension"]
    # Internal keys and runtime should be filtered out
    assert "_internal_key" not in ctx
    assert "runtime" not in ctx


def test_discover_sources_includes_context_json(tmp_path: Path) -> None:
    """context.json should be discovered as a result file by _result_files."""
    cache_dir = tmp_path / "cache"
    source_dir = paths.source_dir(cache_dir, "ctx111")
    (source_dir / "context.json").write_text(
        json.dumps({"doc_type": "lab_result", "summary": "Normal values"}),
        encoding="utf-8",
    )
    (source_dir / "metadata.json").write_text(
        json.dumps({"display_name": "Lab Report", "source": "lab.pdf"}),
        encoding="utf-8",
    )

    discovered = discover_sources(cache_dir)
    assert len(discovered) == 1
    assert discovered[0].source_id == "ctx111"
    file_names = [f.name for f in discovered[0].files]
    assert "context.json" in file_names


def test_discover_sources_context_json_ordering(tmp_path: Path) -> None:
    """context.json should appear after summary files but before transcript.txt."""
    cache_dir = tmp_path / "cache"
    source_dir = paths.source_dir(cache_dir, "ord111")
    (source_dir / "summary-full.md").write_text("summary", encoding="utf-8")
    (source_dir / "context.json").write_text('{"k": "v"}', encoding="utf-8")
    (source_dir / "transcript.txt").write_text("transcript", encoding="utf-8")
    (source_dir / "metadata.json").write_text(
        json.dumps({"display_name": "Test", "source": "test.mp3"}),
        encoding="utf-8",
    )

    discovered = discover_sources(cache_dir)
    assert len(discovered) == 1
    names = [f.name for f in discovered[0].files]
    assert names.index("summary-full.md") < names.index("context.json")
    assert names.index("context.json") < names.index("transcript.txt")


# ── Tests for step progress and on_step_complete callback ────────────────────


def test_worker_invokes_on_step_complete_and_persists_step_progress(tmp_path: Path, monkeypatch) -> None:
    """The worker's _on_step_complete closure writes step_progress into context.json."""
    cache_dir = tmp_path / "cache"
    config = _make_config(cache_dir)
    trigger_dir = tmp_path / "empty-triggers"
    trigger_dir.mkdir()
    config = dataclasses.replace(config, triggers_dir=trigger_dir)
    enqueue_jobs(
        cache_dir,
        sources=["progress-test.pdf"],
        workflow_name="clinical_doc_triage",
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
    )

    callback_calls: list[dict] = []

    def fake_execute_source_workflow(
        config,
        *,
        source,
        workflow_name,
        params,
        no_cache,
        verbose,
        progress,
        on_step_complete=None,
    ):
        source_id = paths.compute_source_id(source)
        ctx = SimpleNamespace(
            source_id=source_id,
            data={
                "display_name": "progress-test.pdf",
                "export_output_path": "",
                "_step_timings": [],
            },
        )
        # Simulate 3 steps completing
        steps = [("Parse PDF", 120), ("Classify", 340), ("Summarize", 1500)]
        for i, (name, dur) in enumerate(steps):
            ctx.data["_step_timings"].append({"name": name, "duration_ms": dur})
            if on_step_complete is not None:
                on_step_complete(ctx, name, i + 1, len(steps))
                callback_calls.append({"step": name, "num": i + 1, "total": len(steps)})
        return ctx

    monkeypatch.setattr("solux.worker.execute_source_workflow", fake_execute_source_workflow)
    rc = run_log_worker(config, poll_interval=0.01, once=True)
    assert rc == 0

    # Verify callback was called for each step
    assert len(callback_calls) == 3
    assert callback_calls[0] == {"step": "Parse PDF", "num": 1, "total": 3}
    assert callback_calls[2] == {"step": "Summarize", "num": 3, "total": 3}

    # Verify step_progress was persisted in context.json
    source_id = paths.compute_source_id("progress-test.pdf")
    ctx_path = paths.source_dir(cache_dir, source_id) / "context.json"
    assert ctx_path.exists()
    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    assert "step_progress" in ctx
    sp = ctx["step_progress"]
    assert sp["completed"] == 3
    assert sp["total"] == 3
    assert sp["current"] == "Summarize"
    assert len(sp["steps"]) == 3
    assert sp["steps"][0]["name"] == "Parse PDF"
    assert sp["steps"][0]["duration_ms"] == 120


def test_execute_workflow_on_step_complete_callback() -> None:
    """execute_workflow calls on_step_complete after each step."""
    import logging
    from solux.workflows.engine import execute_workflow
    from solux.workflows.models import Context, Step, Workflow
    from solux.workflows.registry import StepRegistry

    def noop_handler(ctx, step):
        ctx.data["touched"] = True
        return ctx

    reg = StepRegistry()
    reg.register("test.noop", noop_handler)

    workflow = Workflow(
        name="test_callback",
        description="test",
        steps=[
            Step(name="step_a", type="test.noop", config={}),
            Step(name="step_b", type="test.noop", config={}),
        ],
    )
    ctx = Context(
        source="test",
        source_id="cb001",
        data={},
        config=None,
        logger=logging.getLogger("test"),
    )

    calls: list[tuple[str, int, int]] = []

    def on_step(ctx, step_name, step_num, total):
        calls.append((step_name, step_num, total))

    result = execute_workflow(workflow, ctx, registry=reg, on_step_complete=on_step)
    assert len(calls) == 2
    assert calls[0] == ("step_a", 1, 2)
    assert calls[1] == ("step_b", 2, 2)
    assert result.data["touched"] is True


def test_execute_workflow_on_step_complete_exception_swallowed() -> None:
    """Exceptions in on_step_complete are silently swallowed."""
    import logging
    from solux.workflows.engine import execute_workflow
    from solux.workflows.models import Context, Step, Workflow
    from solux.workflows.registry import StepRegistry

    def noop_handler(ctx, step):
        return ctx

    reg = StepRegistry()
    reg.register("test.noop", noop_handler)

    workflow = Workflow(
        name="test_exc",
        description="test",
        steps=[Step(name="step_a", type="test.noop", config={})],
    )
    ctx = Context(
        source="test",
        source_id="exc001",
        data={},
        config=None,
        logger=logging.getLogger("test"),
    )

    def on_step_boom(ctx, step_name, step_num, total):
        raise RuntimeError("callback error")

    # Should not raise
    result = execute_workflow(workflow, ctx, registry=reg, on_step_complete=on_step_boom)
    assert result is not None
