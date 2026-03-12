from __future__ import annotations

import errno
import json
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import (
    db_claim_next_pending_job,
    db_count_jobs,
    db_enqueue_jobs,
    db_prune_jobs,
    db_queue_counts,
    db_read_job,
    db_read_jobs,
    db_repair_queue,
    db_reset_processing_jobs,
    db_retry_failed_jobs,
    db_update_job,
)

_JOBS_THREAD_LOCK = threading.Lock()
_LOCK_BYTES = 1

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def queue_dir(cache_dir: Path) -> Path:
    path = cache_dir / "queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def jobs_path(cache_dir: Path) -> Path:
    return queue_dir(cache_dir) / "jobs.json"


def worker_lock_path(cache_dir: Path) -> Path:
    return queue_dir(cache_dir) / "worker.lock"


def jobs_lock_path(cache_dir: Path) -> Path:
    return queue_dir(cache_dir) / "jobs.lock"


def worker_log_path(cache_dir: Path) -> Path:
    return queue_dir(cache_dir) / "worker.log"


def worker_pid_path(cache_dir: Path) -> Path:
    return queue_dir(cache_dir) / "worker.pid"


def write_worker_pid(cache_dir: Path, pid: int) -> None:
    path = worker_pid_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def read_worker_pid(cache_dir: Path) -> int | None:
    path = worker_pid_path(cache_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        return int(text)
    except (OSError, ValueError):
        return None


def clear_worker_pid(cache_dir: Path) -> None:
    path = worker_pid_path(cache_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def current_worker_pid(cache_dir: Path) -> int | None:
    pid = read_worker_pid(cache_dir)
    if pid is None:
        return None
    if is_pid_running(pid):
        return pid
    clear_worker_pid(cache_dir)
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prepare_lock_file(fh) -> None:
    if os.name != "nt":
        return
    fh.seek(0, os.SEEK_END)
    if fh.tell() == 0:
        fh.write("\n")
        fh.flush()
    fh.seek(0)


def _lock_exclusive(fh, *, non_blocking: bool = False) -> None:
    _prepare_lock_file(fh)
    if os.name == "nt":
        mode_name = "LK_NBLCK" if non_blocking else "LK_LOCK"
        mode = getattr(msvcrt, mode_name, None)
        lock_fn = getattr(msvcrt, "locking", None)
        if not isinstance(mode, int) or not callable(lock_fn):
            raise RuntimeError("Windows file locking APIs are unavailable in msvcrt")
        try:
            lock_fn(fh.fileno(), mode, _LOCK_BYTES)
        except OSError as exc:
            if non_blocking and (
                exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(exc, "winerror", None) in {33, 36}
            ):
                raise BlockingIOError from exc
            raise
        return
    mode = fcntl.LOCK_EX | (fcntl.LOCK_NB if non_blocking else 0)
    fcntl.flock(fh.fileno(), mode)


def _unlock(fh) -> None:
    if os.name == "nt":
        fh.seek(0)
        unlock_mode = getattr(msvcrt, "LK_UNLCK", None)
        lock_fn = getattr(msvcrt, "locking", None)
        if not isinstance(unlock_mode, int) or not callable(lock_fn):
            raise RuntimeError("Windows file locking APIs are unavailable in msvcrt")
        lock_fn(fh.fileno(), unlock_mode, _LOCK_BYTES)
        return
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _JOBS_THREAD_LOCK:
        with lock_path.open("a+", encoding="utf-8") as fh:
            _lock_exclusive(fh)
            try:
                yield
            finally:
                _unlock(fh)


@contextmanager
def try_worker_lock(cache_dir: Path):
    lock_file = worker_lock_path(cache_dir)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as fh:
        try:
            _lock_exclusive(fh, non_blocking=True)
            acquired = True
        except BlockingIOError:
            acquired = False
        try:
            yield acquired
        finally:
            if acquired:
                _unlock(fh)


def _params_from_legacy(job: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if "mode" in job:
        params["mode"] = job.get("mode")
    if "format" in job:
        params["format"] = job.get("format")
    if "timestamps" in job:
        params["timestamps"] = bool(job.get("timestamps", False))
    if "no_cache" in job:
        params["no_cache"] = bool(job.get("no_cache", False))
    if "model" in job and job.get("model") is not None:
        params["model"] = job.get("model")
    return params


def _normalize_job(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    workflow_name = str(normalized.get("workflow_name") or "audio_summary")
    params = normalized.get("params")
    if not isinstance(params, dict):
        params = {}
    legacy_params = _params_from_legacy(normalized)
    for key, value in legacy_params.items():
        params.setdefault(key, value)

    normalized["workflow_name"] = workflow_name
    normalized["params"] = params

    # Compatibility mirrors for old UI/tests.
    if "mode" not in normalized and "mode" in params:
        normalized["mode"] = params.get("mode")
    if "format" not in normalized and "format" in params:
        normalized["format"] = params.get("format")
    if "timestamps" not in normalized and "timestamps" in params:
        normalized["timestamps"] = bool(params.get("timestamps"))
    if "no_cache" not in normalized and "no_cache" in params:
        normalized["no_cache"] = bool(params.get("no_cache"))
    if "model" not in normalized and "model" in params:
        normalized["model"] = params.get("model")
    return normalized


def _read_jobs_unlocked(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        bak = path.with_suffix(".bak")
        print(
            f"[queueing] Warning: failed to read {path} ({exc}); attempting backup {bak}",
            file=sys.stderr,
        )
        if bak.exists():
            try:
                raw = json.loads(bak.read_text(encoding="utf-8"))
                print(f"[queueing] Recovered jobs from backup {bak}", file=sys.stderr)
            except (OSError, json.JSONDecodeError) as bak_exc:
                print(f"[queueing] Warning: backup also unreadable: {bak_exc}", file=sys.stderr)
                return []
        else:
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(_normalize_job(item))
    return out


def _write_jobs_unlocked(path: Path, jobs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        bak = path.with_suffix(".bak")
        try:
            import shutil as _shutil

            _shutil.copy2(path, bak)
        except OSError:
            pass
    tmp = path.with_suffix(".tmp")
    sanitized = [_normalize_job(job) for job in jobs]
    tmp.write_text(json.dumps(sanitized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_jobs(
    cache_dir: Path,
    *,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = False,
) -> list[dict[str, Any]]:
    return db_read_jobs(cache_dir, limit=limit, offset=offset, newest_first=newest_first)


def read_job(cache_dir: Path, job_id: str) -> dict[str, Any] | None:
    return db_read_job(cache_dir, job_id)


def count_jobs(cache_dir: Path) -> int:
    return db_count_jobs(cache_dir)


def enqueue_jobs(
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
    return db_enqueue_jobs(
        cache_dir,
        sources,
        workflow_name=workflow_name,
        params=params,
        mode=mode,
        output_format=output_format,
        timestamps=timestamps,
        no_cache=no_cache,
        model=model,
    )


def claim_next_pending_job(cache_dir: Path) -> dict[str, Any] | None:
    return db_claim_next_pending_job(cache_dir)


def update_job(cache_dir: Path, job_id: str, **updates: Any) -> bool:
    return db_update_job(cache_dir, job_id, **updates)


def queue_counts(cache_dir: Path) -> dict[str, int]:
    return db_queue_counts(cache_dir)


def append_worker_log(cache_dir: Path, message: str) -> None:
    path = worker_log_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{_utc_now()}] {message}\n")


def retry_failed_jobs(
    cache_dir: Path,
    job_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Reset failed/dead-letter jobs back to pending. Returns reset jobs."""
    return db_retry_failed_jobs(cache_dir, job_ids=job_ids)


def reset_processing_jobs(cache_dir: Path) -> int:
    """Reset all jobs in 'processing' state back to 'pending'. Returns reset count."""
    return db_reset_processing_jobs(cache_dir)


def repair_queue(cache_dir: Path) -> dict[str, int]:
    """
    Rebuild the queue from the filesystem:
    - Add synthetic 'done' entries for source dirs that have results but no job
    - Reset stuck 'processing' jobs to 'pending'
    Returns stats dict with keys: added, reset
    """
    return db_repair_queue(cache_dir)


def prune_jobs(
    cache_dir: Path,
    *,
    statuses: set[str] | None = None,
    source_id: str | None = None,
    stale_only: bool = False,
) -> dict[str, int]:
    """
    Remove queue jobs matching filters.

    - statuses: statuses to remove (default caller-defined)
    - source_id: if set, only remove jobs for this source_id
    - stale_only: remove only jobs whose source_id directory is missing
    Returns stats: removed, remaining
    """
    return db_prune_jobs(cache_dir, statuses=statuses, source_id=source_id, stale_only=stale_only)
