from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from ..background import start_background_worker
from ..config import ConfigError, load_config
from ..queueing import (
    clear_worker_pid,
    current_worker_pid,
    is_pid_running,
    queue_counts,
    read_worker_pid,
    try_worker_lock,
    worker_log_path,
)
from ..worker import run_log_worker


def cmd_worker_start(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    started, pid, reason = start_background_worker(
        config.paths.cache_dir,
        poll_interval=args.poll_interval,
        workers=args.workers,
    )
    if started:
        print(f"Worker started (pid={pid}, workers={max(1, args.workers)}).")
        return 0
    if reason == "already-running":
        print(f"Worker already running (pid={pid}).")
        return 0
    if reason == "start-failed":
        print(
            "Worker failed to start and exited immediately. "
            "Run `python -m solux.cli worker start --_run-loop` to inspect startup errors.",
            file=sys.stderr,
        )
        return 1
    print("Worker appears to be running (lock held) but no pid file is available.")
    print("If this is stale, stop old worker processes and run `solux worker stop` again.")
    return 1


def cmd_worker_stop(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    cache_dir = config.paths.cache_dir
    pid = current_worker_pid(cache_dir)
    if pid is None:
        with try_worker_lock(cache_dir) as acquired:
            lock_held = not acquired
        if lock_held:
            print("Worker lock is held, but no worker pid is recorded.")
            print("Stop the worker process manually, then run `solux worker status`.")
            return 1
        clear_worker_pid(cache_dir)
        print("Worker is not running.")
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_worker_pid(cache_dir)
        print(f"Worker pid {pid} was not running; cleared stale pid file.")
        return 0
    except OSError as exc:
        print(f"Failed to stop worker pid {pid}: {exc}", file=sys.stderr)
        return 1

    deadline = time.time() + max(0.1, args.timeout)
    while time.time() < deadline:
        if not is_pid_running(pid):
            clear_worker_pid(cache_dir)
            print(f"Worker stopped (pid={pid}).")
            return 0
        time.sleep(0.1)

    if args.force:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError as exc:
            print(f"Failed to force-stop worker pid {pid}: {exc}", file=sys.stderr)
            return 1
        time.sleep(0.1)
        if is_pid_running(pid):
            print(f"Worker pid {pid} did not exit after SIGKILL.", file=sys.stderr)
            return 1
        clear_worker_pid(cache_dir)
        print(f"Worker force-stopped (pid={pid}).")
        return 0

    print(
        f"Worker pid {pid} did not stop within {args.timeout:.1f}s. Run `solux worker stop --force` if needed.",
        file=sys.stderr,
    )
    return 1


def cmd_worker_status() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    cache_dir = config.paths.cache_dir
    pid_file_value = read_worker_pid(cache_dir)
    running_pid = current_worker_pid(cache_dir)
    with try_worker_lock(cache_dir) as acquired:
        lock_held = not acquired
    counts = queue_counts(cache_dir)

    if running_pid is not None:
        status = f"running (pid={running_pid})"
    elif lock_held:
        if pid_file_value is not None:
            status = f"running (pid file has stale/unknown pid={pid_file_value}; lock held)"
        else:
            status = "running (pid unknown; lock held)"
    else:
        status = "stopped"

    print(f"Worker status: {status}")
    print(
        "Queue counts: "
        f"pending={counts['pending']} processing={counts['processing']} "
        f"done={counts['done']} failed={counts['failed']} dead_letter={counts['dead_letter']}"
    )
    print(f"Worker log: {worker_log_path(cache_dir)}")
    return 0


def cmd_worker_internal(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        return run_log_worker(
            config,
            poll_interval=args.poll_interval,
            once=args.once,
            workers=args.workers,
        )
    finally:
        recorded = read_worker_pid(config.paths.cache_dir)
        if recorded == os.getpid():
            clear_worker_pid(config.paths.cache_dir)


def cmd_worker(args: argparse.Namespace) -> int:
    action = getattr(args, "worker_action", "status")
    if action == "start":
        if getattr(args, "_run_loop", False):
            return cmd_worker_internal(args)
        return cmd_worker_start(args)
    if action == "stop":
        return cmd_worker_stop(args)
    if action == "status":
        return cmd_worker_status()
    print(f"Unknown worker action: {action}", file=sys.stderr)
    return 1
