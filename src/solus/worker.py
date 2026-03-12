from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, effective_external_modules_dir
from .db import db_move_to_dead_letter, db_schedule_retry
from .paths import source_dir as _source_dir
from .pipeline import execute_source_workflow
from .queueing import (
    append_worker_log,
    claim_next_pending_job,
    queue_counts,
    reset_processing_jobs,
    try_worker_lock,
    update_job,
    worker_log_path,
)
from .reload import HotReloader
from .triggers import load_triggers, run_triggers
from .workflows.engine import StepTimeoutError

_RETRY_BASE_DELAY_SECONDS = 30
_SENSITIVE_PARAM_RE = re.compile(r"(pass|secret|token|auth|key|credential)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_log(cache_dir, message: str) -> None:
    print(message, flush=True)
    append_worker_log(cache_dir, message)


def _sanitize_for_log(value):
    if isinstance(value, dict):
        cleaned = {}
        for k, v in value.items():
            key = str(k)
            if _SENSITIVE_PARAM_RE.search(key):
                cleaned[key] = "***"
            else:
                cleaned[key] = _sanitize_for_log(v)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_for_log(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_for_log(v) for v in value)
    return value


def _safe_value(value):
    """Convert a value to a JSON-serializable type."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(v) for v in value]
    return str(value)


def _persist_context(cache_dir, ctx) -> None:
    """Write ctx.data as context.json in the source directory."""
    try:
        sid = getattr(ctx, "source_id", None)
        if not sid:
            return
        data = getattr(ctx, "data", None)
        if not data or not isinstance(data, dict):
            return
        filtered = {k: _safe_value(v) for k, v in data.items() if not k.startswith("_") and k != "runtime"}
        if not filtered:
            return
        out_path = _source_dir(cache_dir, sid) / "context.json"
        out_path.write_text(
            json.dumps(filtered, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


def _process_one_job_loop(
    config: Config,
    poll_interval: float,
    once: bool,
    cache_dir,
    worker_id: str,
    stop_event: threading.Event,
) -> int:
    """Inner job-claim-process-update loop for a single worker thread."""
    last_idle_log = 0.0
    while not stop_event.is_set():
        job = claim_next_pending_job(cache_dir)
        if job is None:
            if once:
                _worker_log(cache_dir, f"[{worker_id}] No pending jobs. Exiting.")
                return 0

            now = time.time()
            if now - last_idle_log >= 15:
                counts = queue_counts(cache_dir)
                _worker_log(
                    cache_dir,
                    f"[{worker_id}] Waiting for jobs... "
                    f"pending={counts['pending']} processing={counts['processing']} "
                    f"done={counts['done']} failed={counts['failed']} dead_letter={counts['dead_letter']}",
                )
                last_idle_log = now
            time.sleep(max(0.2, poll_interval))
            continue

        job_id = str(job.get("job_id", "<unknown>"))
        source = str(job.get("source", ""))
        workflow_name = str(job.get("workflow_name") or "audio_summary")
        params = dict(job.get("params") or {})
        no_cache = bool(params.get("no_cache", False))
        safe_params = _sanitize_for_log(params)

        _worker_log(
            cache_dir,
            f"[{job_id}] Processing workflow={workflow_name} source={source!r} params={safe_params}",
        )
        counts = queue_counts(cache_dir)
        _worker_log(
            cache_dir,
            f"[{job_id}] Queue length: pending={counts['pending']} "
            f"processing={counts['processing']} done={counts['done']} "
            f"failed={counts['failed']} dead_letter={counts['dead_letter']}",
        )

        def progress(message: str) -> None:
            _worker_log(cache_dir, f"[{job_id}] {message}")

        def _on_step_complete(ctx, step_name, step_num, total_steps):
            timings = ctx.data.get("_step_timings", [])
            ctx.data["step_progress"] = {
                "completed": step_num,
                "total": total_steps,
                "current": step_name,
                "steps": [{"name": t["name"], "duration_ms": t.get("duration_ms", 0)} for t in timings],
            }
            _persist_context(cache_dir, ctx)

        try:
            ctx = execute_source_workflow(
                config=config,
                source=source,
                workflow_name=workflow_name,
                params=params,
                no_cache=no_cache,
                verbose=True,
                progress=progress,
                on_step_complete=_on_step_complete,
            )
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            tb = traceback.format_exc(limit=8)

            retry_count = int(job.get("retry_count") or 0)
            max_retries = int(job.get("max_retries") or 3)

            if isinstance(exc, StepTimeoutError):
                update_job(
                    cache_dir,
                    job_id,
                    status="failed",
                    finished_at=_now(),
                    error=err,
                    traceback=tb,
                )
                db_move_to_dead_letter(cache_dir, job_id)
                _worker_log(
                    cache_dir,
                    f"[{job_id}] DEAD LETTER (timeout): {err}. Retries are skipped to avoid duplicate side effects.",
                )
                counts = queue_counts(cache_dir)
                _worker_log(
                    cache_dir,
                    f"[{job_id}] Queue length after failure: pending={counts['pending']} "
                    f"processing={counts['processing']} done={counts['done']} "
                    f"failed={counts['failed']} dead_letter={counts['dead_letter']}",
                )
                continue

            if retry_count < max_retries:
                delay = _RETRY_BASE_DELAY_SECONDS * (2**retry_count)
                update_job(
                    cache_dir,
                    job_id,
                    status="failed",
                    finished_at=_now(),
                    error=err,
                    traceback=tb,
                )
                db_schedule_retry(cache_dir, job_id, delay)
                _worker_log(
                    cache_dir,
                    f"[{job_id}] FAILED (attempt {retry_count + 1}/{max_retries + 1}): {err}. Retrying in {delay}s.",
                )
            else:
                update_job(
                    cache_dir,
                    job_id,
                    status="failed",
                    finished_at=_now(),
                    error=err,
                    traceback=tb,
                )
                db_move_to_dead_letter(cache_dir, job_id)
                _worker_log(cache_dir, f"[{job_id}] DEAD LETTER after {max_retries + 1} attempts: {err}")

            counts = queue_counts(cache_dir)
            _worker_log(
                cache_dir,
                f"[{job_id}] Queue length after failure: pending={counts['pending']} "
                f"processing={counts['processing']} done={counts['done']} "
                f"failed={counts['failed']} dead_letter={counts['dead_letter']}",
            )
            continue

        _persist_context(cache_dir, ctx)
        output_path = str(ctx.data.get("export_output_path", ""))
        update_job(
            cache_dir,
            job_id,
            status="done",
            finished_at=_now(),
            source_id=ctx.source_id,
            display_name=str(ctx.data.get("display_name") or source),
            output_path=output_path,
            workflow_name=workflow_name,
            params=params,
        )
        _worker_log(cache_dir, f"[{job_id}] DONE -> {output_path}")
        counts = queue_counts(cache_dir)
        _worker_log(
            cache_dir,
            f"[{job_id}] Queue length after completion: pending={counts['pending']} "
            f"processing={counts['processing']} done={counts['done']} "
            f"failed={counts['failed']} dead_letter={counts['dead_letter']}",
        )

    return 0


def run_log_worker(
    config: Config,
    *,
    poll_interval: float = 2.0,
    once: bool = False,
    workers: int = 1,
) -> int:
    cache_dir = config.paths.cache_dir
    with try_worker_lock(cache_dir) as acquired:
        if not acquired:
            print("Another queue worker is already running. Use `solus worker status` to inspect.")
            return 1

        recovered = reset_processing_jobs(cache_dir)
        _worker_log(cache_dir, f"Worker started at {_now()} (cache_dir={cache_dir}, workers={workers})")
        if recovered:
            _worker_log(
                cache_dir,
                f"Recovered {recovered} stuck processing job(s): reset to pending.",
            )
        counts = queue_counts(cache_dir)
        _worker_log(
            cache_dir,
            "Queue counts: "
            f"pending={counts['pending']} processing={counts['processing']} "
            f"done={counts['done']} failed={counts['failed']} dead_letter={counts['dead_letter']}",
        )

        stop_event = threading.Event()

        trigger_stop_event = threading.Event()
        trigger_threads: list[threading.Thread] = []
        trigger_lock = threading.Lock()

        def _stop_trigger_threads() -> None:
            nonlocal trigger_threads
            trigger_stop_event.set()
            for thread in trigger_threads:
                thread.join(timeout=2.0)
            trigger_threads = []

        def _restart_triggers() -> None:
            nonlocal trigger_stop_event, trigger_threads
            with trigger_lock:
                _stop_trigger_threads()
                trigger_stop_event = threading.Event()
                trig_dir = getattr(config, "triggers_dir", None)
                loaded, load_errors = load_triggers(trig_dir)
                for err in load_errors:
                    _worker_log(cache_dir, f"[trigger] Warning: {err}")
                if loaded:
                    enabled_count = sum(1 for trig in loaded if bool(getattr(trig, "enabled", True)))
                    _worker_log(cache_dir, f"Starting {enabled_count}/{len(loaded)} enabled trigger(s).")
                    trigger_threads = run_triggers(
                        cache_dir,
                        loaded,
                        stop_event=trigger_stop_event,
                        config=config,
                    )

        # Start/restart triggers once at boot using configured triggers dir.
        _restart_triggers()

        # Start hot-reload watcher (modules/workflows/triggers).
        hot_reloader = HotReloader(
            modules_dir=effective_external_modules_dir(config),
            workflows_dir=getattr(config, "workflows_dir", None),
            triggers_dir=getattr(config, "triggers_dir", None),
            interval=5.0,
            on_reload=_restart_triggers,
        )
        hot_reloader.start()
        _worker_log(cache_dir, "Hot-reload watcher started.")

        try:
            if workers <= 1:
                return _process_one_job_loop(config, poll_interval, once, cache_dir, "worker", stop_event)

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        _process_one_job_loop,
                        config,
                        poll_interval,
                        once,
                        cache_dir,
                        f"worker-{i + 1}",
                        stop_event,
                    )
                    for i in range(workers)
                ]
                concurrent.futures.wait(futures)
            return 0
        except KeyboardInterrupt:
            _worker_log(cache_dir, "Worker stopped by user.")
            return 0
        finally:
            stop_event.set()
            hot_reloader.stop()
            with trigger_lock:
                _stop_trigger_threads()


def run_log_viewer(
    config: Config,
    *,
    poll_interval: float = 2.0,
    show_existing: bool = True,
) -> int:
    cache_dir = config.paths.cache_dir
    log_path = worker_log_path(cache_dir)
    last_queue_counts: dict[str, int] | None = None
    offset = 0

    print(f"Monitoring queue/worker logs in {cache_dir}")
    print("This command is read-only. Press Ctrl-C to stop.")

    def _read_new_lines(path: Path, start: int) -> tuple[int, list[str]]:
        if not path.exists():
            return 0 if start and not path.exists() else start, []
        size = path.stat().st_size
        if start > size:
            start = 0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(start)
            data = fh.read()
            end = fh.tell()
        lines = data.splitlines()
        return end, lines

    try:
        if show_existing and log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()[-200:]
            if lines:
                print("----- recent worker.log -----")
                for line in lines:
                    print(line)
                print("----- live -----")
            offset = log_path.stat().st_size

        while True:
            counts = queue_counts(cache_dir)
            if counts != last_queue_counts:
                print(
                    "[queue] "
                    f"pending={counts['pending']} processing={counts['processing']} "
                    f"done={counts['done']} failed={counts['failed']} dead_letter={counts['dead_letter']}",
                    flush=True,
                )
                last_queue_counts = counts

            offset, lines = _read_new_lines(log_path, offset)
            for line in lines:
                print(line, flush=True)

            time.sleep(max(0.2, poll_interval))
    except KeyboardInterrupt:
        print("\nLog monitor stopped.")
        return 0
