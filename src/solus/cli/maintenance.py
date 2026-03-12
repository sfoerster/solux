from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys

from ..cleanup import run_cleanup
from ..config import ConfigError, ensure_config_file, get_default_config_path, load_config
from ..doctor import run_doctor
from ..queueing import retry_failed_jobs, repair_queue, try_worker_lock


def cmd_doctor(args: argparse.Namespace | None = None) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    workflow_name = str(getattr(args, "workflow", "") or "").strip() or None
    return run_doctor(config, workflow_name=workflow_name)


def cmd_config_edit() -> int:
    """Open config.toml in $EDITOR (or a fallback editor)."""
    config_path = get_default_config_path()
    try:
        _, created = ensure_config_file(config_path)
    except OSError as exc:
        print(f"Failed to create config file at {config_path}: {exc}", file=sys.stderr)
        return 1

    if created:
        print(f"Created config file: {config_path}")

    editor = (
        os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or ("nano" if shutil.which("nano") else None)
        or ("vi" if shutil.which("vi") else None)
    )
    if editor is None:
        print(f"No editor found. Set $EDITOR or edit manually: {config_path}", file=sys.stderr)
        return 1

    try:
        cmd = shlex.split(editor, posix=os.name != "nt")
    except ValueError as exc:
        print(f"Failed to parse editor command '{editor}': {exc}", file=sys.stderr)
        return 1
    if not cmd:
        print(f"Invalid editor command '{editor}'. Edit manually: {config_path}", file=sys.stderr)
        return 1

    try:
        subprocess.run([*cmd, str(config_path)], check=False)
    except FileNotFoundError:
        print(f"Editor '{cmd[0]}' not found. Edit manually: {config_path}", file=sys.stderr)
        return 1

    print(f"\nConfig saved to {config_path}")
    print("Run `solus config` to validate and see the doctor report.")
    return 0


def cmd_config() -> int:
    config_path = get_default_config_path()
    try:
        _, created = ensure_config_file(config_path)
    except OSError as exc:
        print(f"Failed to create config file at {config_path}: {exc}", file=sys.stderr)
        return 1

    if created:
        print(f"Created config file: {config_path}")
    else:
        print(f"Config file already exists: {config_path}")

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Failed to read config file at {config_path}: {exc}", file=sys.stderr)
        return 1

    print("\n# config.toml")
    print(content.rstrip())
    print("\n# doctor")

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    return run_doctor(config)


def cmd_cleanup(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    return run_cleanup(
        config=config,
        source_id=args.source_id,
        yes=args.yes,
        dry_run=args.dry_run,
        artifacts_only=args.artifacts_only,
        finished_only=args.finished_only,
        older_than_days=args.older_than_days,
        jobs=args.jobs,
        jobs_stale_only=args.jobs_stale_only,
        jobs_all_statuses=args.jobs_all_statuses,
    )


def cmd_retry(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    job_ids = args.job_ids or None
    reset = retry_failed_jobs(config.paths.cache_dir, job_ids=job_ids)
    if not reset:
        print("No failed or dead-letter jobs found to retry.")
        return 0
    print(f"Reset {len(reset)} job(s) to pending:")
    for job in reset:
        print(f"  - {job['job_id']}  [{job.get('workflow_name', 'audio_summary')}]  {job.get('source', '')}")
    return 0


def cmd_repair() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    with try_worker_lock(config.paths.cache_dir) as acquired:
        if not acquired:
            print("Cannot repair queue while background worker is running. Wait or stop it and retry.")
            return 1
        stats = repair_queue(config.paths.cache_dir)

    print(
        f"Queue repaired: {stats['added']} synthetic done-job(s) added, "
        f"{stats['reset']} stuck processing job(s) reset to pending."
    )
    return 0
