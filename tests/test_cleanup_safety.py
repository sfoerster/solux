"""Tests for cleanup module: target collection, age filtering, flag validation,
dry-run, artifact cleanup, and empty directory removal."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from solus.cleanup import (
    _collect_all_targets,
    _collect_artifact_targets,
    _collect_finished_targets,
    _count_files_and_size,
    _human_size,
    _is_finished_source,
    _is_metadata_file,
    _is_result_file,
    _iter_source_dirs,
    _remove_empty_dirs_under,
    _source_last_update,
    run_cleanup,
)
from solus.config import Config, PathsConfig


def _make_config(cache_dir: Path) -> Config:
    from unittest.mock import MagicMock

    config = MagicMock(spec=Config)
    config.paths = MagicMock(spec=PathsConfig)
    config.paths.cache_dir = cache_dir
    return config


def _create_source(cache_dir: Path, source_id: str, files: dict[str, str] | None = None):
    """Create a source directory with optional files."""
    source_dir = cache_dir / "sources" / source_id
    source_dir.mkdir(parents=True, exist_ok=True)
    if files:
        for name, content in files.items():
            (source_dir / name).write_text(content, encoding="utf-8")
    return source_dir


# ---------------------------------------------------------------------------
# File classification helpers
# ---------------------------------------------------------------------------


class TestFileClassification:
    def test_is_result_file(self) -> None:
        assert _is_result_file(Path("transcript.txt")) is True
        assert _is_result_file(Path("summary-full.md")) is True
        assert _is_result_file(Path("summary-tldr.md")) is True
        assert _is_result_file(Path("audio.wav")) is False

    def test_is_metadata_file(self) -> None:
        assert _is_metadata_file(Path("metadata.json")) is True
        assert _is_metadata_file(Path("data.json")) is False


# ---------------------------------------------------------------------------
# _count_files_and_size
# ---------------------------------------------------------------------------


class TestCountFilesAndSize:
    def test_counts_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "b.txt").write_text("world", encoding="utf-8")
        count, size = _count_files_and_size(tmp_path)
        assert count == 2
        assert size == 10

    def test_empty_dir(self, tmp_path: Path) -> None:
        count, size = _count_files_and_size(tmp_path)
        assert count == 0
        assert size == 0

    def test_nested_files(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("x", encoding="utf-8")
        count, _ = _count_files_and_size(tmp_path)
        assert count == 1


# ---------------------------------------------------------------------------
# _human_size
# ---------------------------------------------------------------------------


class TestHumanSize:
    def test_bytes(self) -> None:
        assert _human_size(500) == "500 B"

    def test_kib(self) -> None:
        result = _human_size(2048)
        assert "KiB" in result

    def test_mib(self) -> None:
        result = _human_size(5 * 1024 * 1024)
        assert "MiB" in result

    def test_zero(self) -> None:
        assert _human_size(0) == "0 B"


# ---------------------------------------------------------------------------
# _iter_source_dirs
# ---------------------------------------------------------------------------


class TestIterSourceDirs:
    def test_no_sources_dir(self, tmp_path: Path) -> None:
        assert _iter_source_dirs(tmp_path) == []

    def test_all_sources(self, tmp_path: Path) -> None:
        _create_source(tmp_path, "src1")
        _create_source(tmp_path, "src2")
        dirs = _iter_source_dirs(tmp_path)
        assert len(dirs) == 2

    def test_specific_source(self, tmp_path: Path) -> None:
        _create_source(tmp_path, "src1")
        _create_source(tmp_path, "src2")
        dirs = _iter_source_dirs(tmp_path, source_id="src1")
        assert len(dirs) == 1
        assert dirs[0].name == "src1"

    def test_nonexistent_source_id(self, tmp_path: Path) -> None:
        _create_source(tmp_path, "src1")
        dirs = _iter_source_dirs(tmp_path, source_id="missing")
        assert dirs == []


# ---------------------------------------------------------------------------
# _is_finished_source
# ---------------------------------------------------------------------------


class TestIsFinishedSource:
    def test_finished_with_transcript(self, tmp_path: Path) -> None:
        source = _create_source(tmp_path, "s1", {"transcript.txt": "text"})
        assert _is_finished_source(source) is True

    def test_finished_with_summary(self, tmp_path: Path) -> None:
        source = _create_source(tmp_path, "s1", {"summary-full.md": "content"})
        assert _is_finished_source(source) is True

    def test_not_finished(self, tmp_path: Path) -> None:
        source = _create_source(tmp_path, "s1", {"audio.wav": "data"})
        assert _is_finished_source(source) is False

    def test_empty_dir(self, tmp_path: Path) -> None:
        source = _create_source(tmp_path, "s1")
        assert _is_finished_source(source) is False


# ---------------------------------------------------------------------------
# _source_last_update
# ---------------------------------------------------------------------------


class TestSourceLastUpdate:
    def test_returns_result_file_mtime(self, tmp_path: Path) -> None:
        source = _create_source(tmp_path, "s1", {"transcript.txt": "text"})
        last = _source_last_update(source)
        assert last > 0

    def test_falls_back_to_dir_mtime(self, tmp_path: Path) -> None:
        source = _create_source(tmp_path, "s1", {"audio.wav": "data"})
        last = _source_last_update(source)
        assert last > 0


# ---------------------------------------------------------------------------
# _collect_finished_targets with age filtering
# ---------------------------------------------------------------------------


class TestCollectFinishedTargets:
    def test_collects_finished_sources(self, tmp_path: Path) -> None:
        _create_source(tmp_path, "s1", {"transcript.txt": "done"})
        _create_source(tmp_path, "s2", {"audio.wav": "processing"})
        targets = _collect_finished_targets(tmp_path, source_id=None, older_than_days=None)
        source_ids = [t.source_id for t in targets if t.kind == "finished_source_dir"]
        assert "s1" in source_ids
        assert "s2" not in source_ids

    def test_age_filter_excludes_recent(self, tmp_path: Path) -> None:
        _create_source(tmp_path, "s1", {"transcript.txt": "done"})
        # Just created, so it's very recent
        targets = _collect_finished_targets(tmp_path, source_id=None, older_than_days=1)
        source_ids = [t.source_id for t in targets if t.kind == "finished_source_dir"]
        assert "s1" not in source_ids

    def test_exports_included_for_finished(self, tmp_path: Path) -> None:
        _create_source(tmp_path, "s1", {"transcript.txt": "done"})
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        (outputs_dir / "ep-s1-full.md").write_text("summary", encoding="utf-8")
        targets = _collect_finished_targets(tmp_path, source_id=None, older_than_days=None)
        kinds = {t.kind for t in targets}
        assert "finished_export" in kinds


# ---------------------------------------------------------------------------
# _collect_artifact_targets
# ---------------------------------------------------------------------------


class TestCollectArtifactTargets:
    def test_includes_non_result_files(self, tmp_path: Path) -> None:
        _create_source(
            tmp_path,
            "s1",
            {
                "transcript.txt": "result",
                "metadata.json": "{}",
                "audio.wav": "raw data",
                "normalized.wav": "processed",
            },
        )
        targets = _collect_artifact_targets(tmp_path, source_id=None)
        artifact_names = {t.path.name for t in targets}
        assert "audio.wav" in artifact_names
        assert "normalized.wav" in artifact_names
        assert "transcript.txt" not in artifact_names
        assert "metadata.json" not in artifact_names


# ---------------------------------------------------------------------------
# _remove_empty_dirs_under
# ---------------------------------------------------------------------------


class TestRemoveEmptyDirs:
    def test_removes_nested_empty(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        _remove_empty_dirs_under(tmp_path / "a")
        assert not (tmp_path / "a").exists()

    def test_keeps_non_empty(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file.txt").write_text("keep", encoding="utf-8")
        _remove_empty_dirs_under(tmp_path)
        assert sub.exists()
        assert (sub / "file.txt").exists()


# ---------------------------------------------------------------------------
# run_cleanup flag validation
# ---------------------------------------------------------------------------


class TestRunCleanupFlags:
    def test_jobs_with_artifacts_only_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, jobs=True, artifacts_only=True)
        assert rc == 1

    def test_jobs_with_finished_only_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, jobs=True, finished_only=True)
        assert rc == 1

    def test_jobs_with_older_than_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, jobs=True, older_than_days=7)
        assert rc == 1

    def test_artifacts_and_finished_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, artifacts_only=True, finished_only=True)
        assert rc == 1

    def test_negative_older_than_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, finished_only=True, older_than_days=-1)
        assert rc == 1

    def test_older_than_without_finished_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, older_than_days=7)
        assert rc == 1

    def test_stale_only_without_jobs_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, jobs_stale_only=True)
        assert rc == 1

    def test_all_statuses_without_jobs_rejected(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        rc = run_cleanup(config, jobs_all_statuses=True)
        assert rc == 1


# ---------------------------------------------------------------------------
# run_cleanup dry-run
# ---------------------------------------------------------------------------


class TestRunCleanupDryRun:
    def test_dry_run_does_not_delete(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        _create_source(cache_dir, "s1", {"audio.wav": "data", "transcript.txt": "text"})
        config = _make_config(cache_dir)
        rc = run_cleanup(config, dry_run=True, yes=True)
        assert rc == 0
        assert (cache_dir / "sources" / "s1" / "audio.wav").exists()

    def test_no_targets_message(self, tmp_path: Path, capsys) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        config = _make_config(cache_dir)
        rc = run_cleanup(config, dry_run=True)
        assert rc == 0
        captured = capsys.readouterr()
        assert "No cleanup targets" in captured.out


# ---------------------------------------------------------------------------
# run_cleanup actual deletion
# ---------------------------------------------------------------------------


class TestRunCleanupDeletion:
    def test_deletes_source_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        _create_source(cache_dir, "s1", {"audio.wav": "data"})
        config = _make_config(cache_dir)
        rc = run_cleanup(config, yes=True)
        assert rc == 0
        assert not (cache_dir / "sources" / "s1").exists()

    def test_artifacts_only_keeps_results(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        _create_source(
            cache_dir,
            "s1",
            {
                "audio.wav": "raw",
                "transcript.txt": "result",
            },
        )
        config = _make_config(cache_dir)
        rc = run_cleanup(config, yes=True, artifacts_only=True)
        assert rc == 0
        assert not (cache_dir / "sources" / "s1" / "audio.wav").exists()
        assert (cache_dir / "sources" / "s1" / "transcript.txt").exists()

    def test_finished_only_keeps_unfinished(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        _create_source(cache_dir, "done1", {"transcript.txt": "done"})
        _create_source(cache_dir, "wip1", {"audio.wav": "processing"})
        config = _make_config(cache_dir)
        rc = run_cleanup(config, yes=True, finished_only=True)
        assert rc == 0
        assert not (cache_dir / "sources" / "done1").exists()
        assert (cache_dir / "sources" / "wip1").exists()
