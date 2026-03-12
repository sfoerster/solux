from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .queueing import (
    clear_worker_pid,
    current_worker_pid,
    is_pid_running,
    read_worker_pid,
    try_worker_lock,
    write_worker_pid,
)


def build_worker_env() -> dict[str, str]:
    env = os.environ.copy()
    src_root = Path(__file__).resolve().parents[1]  # .../src
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{src_root}:{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(src_root)
    return env


def start_background_worker(cache_dir: Path, *, poll_interval: float, workers: int) -> tuple[bool, int | None, str]:
    pid = current_worker_pid(cache_dir)
    if pid is not None:
        return False, pid, "already-running"

    with try_worker_lock(cache_dir) as acquired:
        lock_held = not acquired
    if lock_held:
        return False, None, "lock-held"

    cmd = [
        sys.executable,
        "-m",
        "solus.cli",
        "worker",
        "start",
        "--_run-loop",
        "--poll-interval",
        str(poll_interval),
        "--workers",
        str(max(1, workers)),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=build_worker_env(),
    )
    # Detect immediate startup failures (for example invalid module invocation).
    time.sleep(0.1)
    if proc.poll() is not None:
        clear_worker_pid(cache_dir)
        return False, None, "start-failed"
    write_worker_pid(cache_dir, proc.pid)
    return True, proc.pid, "started"


def ensure_background_worker(cache_dir: Path) -> bool:
    started, _, _ = start_background_worker(cache_dir, poll_interval=2.0, workers=1)
    return started


def stop_background_worker(cache_dir: Path, *, timeout: float = 10.0) -> tuple[bool, str]:
    """Stop the background worker. Returns (stopped, message)."""
    pid = current_worker_pid(cache_dir)
    if pid is None:
        with try_worker_lock(cache_dir) as acquired:
            lock_held = not acquired
        if lock_held:
            return False, "lock-held"
        clear_worker_pid(cache_dir)
        return False, "not-running"

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        clear_worker_pid(cache_dir)
        return True, "stale-cleared"
    except OSError:
        return False, "signal-failed"

    deadline = time.time() + max(0.1, timeout)
    while time.time() < deadline:
        if not is_pid_running(pid):
            clear_worker_pid(cache_dir)
            return True, "stopped"
        time.sleep(0.1)

    return False, "timeout"


def worker_status(cache_dir: Path) -> dict[str, object]:
    """Return worker status info as a dict."""
    pid_file_value = read_worker_pid(cache_dir)
    running_pid = current_worker_pid(cache_dir)
    with try_worker_lock(cache_dir) as acquired:
        lock_held = not acquired

    if running_pid is not None:
        return {"status": "running", "pid": running_pid}
    if lock_held:
        return {"status": "running", "pid": pid_file_value}
    return {"status": "stopped", "pid": None}
