from __future__ import annotations

import argparse
import sys

from ..background import ensure_background_worker
from ..config import ConfigError, default_workflow_name, load_config
from ..queueing import enqueue_jobs, queue_counts, worker_log_path
from ..worker import run_log_viewer


def _collect_ingest_sources(args: argparse.Namespace) -> list[str]:
    sources = list(args.sources or [])
    if args.from_file:
        try:
            raw_lines = args.from_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise RuntimeError(f"Failed to read --from-file {args.from_file}: {exc}") from exc
        for line in raw_lines:
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            sources.append(item)
    return sources


def _build_run_params(args: argparse.Namespace) -> dict[str, object]:
    params: dict[str, object] = {
        "mode": args.mode,
        "format": args.format,
        "timestamps": args.timestamps,
        "no_cache": args.no_cache,
    }
    if args.model is not None:
        params["model"] = args.model
    return params


def cmd_ingest(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        sources = _collect_ingest_sources(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not sources:
        print("Error: no sources provided. Pass sources directly or use --from-file.", file=sys.stderr)
        return 1

    params = _build_run_params(args)
    created = enqueue_jobs(
        config.paths.cache_dir,
        sources=sources,
        workflow_name=str(args.workflow or default_workflow_name(config)),
        params=params,
    )
    print(f"Queued {len(created)} job(s).")
    for job in created:
        print(f"- {job['job_id']}  [{job['workflow_name']}]  {job['source']}")
    counts = queue_counts(config.paths.cache_dir)
    print(
        "Queue counts: "
        f"pending={counts['pending']} processing={counts['processing']} "
        f"done={counts['done']} failed={counts['failed']} dead_letter={counts['dead_letter']}"
    )
    started = ensure_background_worker(config.paths.cache_dir)
    if started:
        print("Started background worker.")
    else:
        print("Background worker already running.")
    print(f"Run `solux log` to monitor. Log file: {worker_log_path(config.paths.cache_dir)}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    return run_log_viewer(
        config,
        poll_interval=args.poll_interval,
        show_existing=not args.no_history,
    )
