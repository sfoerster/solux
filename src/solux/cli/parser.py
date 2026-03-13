from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solux",
        description="Solux: local-first AI workflow engine.",
    )
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")

    run_parser = subparsers.add_parser(
        "run",
        help="Run a workflow for one source",
    )
    run_parser.add_argument(
        "source",
        help="Input source (URL or local file path)",
    )
    run_parser.add_argument(
        "--workflow",
        default=None,
        help="Workflow name (default: config ui.default_workflow)",
    )
    run_parser.add_argument(
        "--mode",
        choices=["transcript", "tldr", "outline", "notes", "full"],
        default="full",
        help="Summary mode override for workflows that support it (default: full)",
    )
    run_parser.add_argument(
        "--format",
        choices=["markdown", "text", "json"],
        default="markdown",
        help="Output format override for workflows that support it (default: markdown)",
    )
    run_parser.add_argument("--output", type=Path, help="Optional output file path")
    run_parser.add_argument(
        "--timestamps",
        action="store_true",
        help="Prefer timestamped information where available",
    )
    run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached artifacts and re-run",
    )
    run_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Stream yt-dlp/ffmpeg/whisper-cli output while processing",
    )
    run_parser.add_argument(
        "--quiet-progress",
        action="store_true",
        help="Suppress stage-level progress logs",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help="Override Ollama model for this run (default: from config)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show execution plan without running",
    )

    workflows_parser = subparsers.add_parser(
        "workflows",
        help="Inspect and manage workflows",
    )
    workflows_sub = workflows_parser.add_subparsers(dest="workflows_action", metavar="COMMAND")
    workflows_sub.add_parser("list", help="List workflow names and descriptions")
    workflows_show = workflows_sub.add_parser("show", help="Show one workflow definition")
    workflows_show.add_argument("name", help="Workflow name")
    workflows_validate = workflows_sub.add_parser("validate", help="Validate workflow pipeline wiring")
    workflows_validate.add_argument("name", help="Workflow name")
    workflows_delete = workflows_sub.add_parser("delete", help="Delete a workflow YAML file")
    workflows_delete.add_argument("name", help="Workflow name (file stem in workflows.d/)")
    workflows_delete.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    workflows_sub.add_parser("examples", help="Print example workflow YAML templates")

    modules_parser = subparsers.add_parser(
        "modules",
        help="Inspect discovered modules",
    )
    modules_sub = modules_parser.add_subparsers(dest="modules_action", metavar="COMMAND")
    modules_sub.add_parser("list", help="List all discovered modules grouped by category")
    modules_inspect = modules_sub.add_parser("inspect", help="Show full metadata for a module")
    modules_inspect.add_argument("name", help="Module name (e.g. source_fetch)")

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Queue one or more sources for asynchronous processing",
    )
    ingest_parser.add_argument(
        "sources",
        nargs="*",
        help="Sources to enqueue (URLs or local file paths)",
    )
    ingest_parser.add_argument(
        "--from-file",
        type=Path,
        help="Read sources from a text file (one per line, '#' comments allowed)",
    )
    ingest_parser.add_argument(
        "--workflow",
        default=None,
        help="Workflow name to enqueue (default: config ui.default_workflow)",
    )
    ingest_parser.add_argument(
        "--mode",
        choices=["transcript", "tldr", "outline", "notes", "full"],
        default="full",
        help="Mode parameter for workflows that support it (default: full)",
    )
    ingest_parser.add_argument(
        "--format",
        choices=["markdown", "text", "json"],
        default="markdown",
        help="Format parameter for workflows that support it (default: markdown)",
    )
    ingest_parser.add_argument(
        "--timestamps",
        action="store_true",
        help="Prefer timestamped information where available",
    )
    ingest_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached downloads/transcripts/summaries and re-run",
    )
    ingest_parser.add_argument(
        "--model",
        default=None,
        help="Override Ollama model for queued jobs (default: from config)",
    )

    subparsers.add_parser(
        "init",
        help="Guided first-run setup: create config, scaffold a workflow, check Ollama",
    )

    subparsers.add_parser(
        "examples",
        help="Print example workflow YAML templates (shorthand for 'workflows examples')",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check local dependencies and configuration",
    )
    doctor_parser.add_argument(
        "--workflow",
        default=None,
        help="Limit checks to dependencies required by one workflow",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help="Show prominent fix commands for each issue",
    )
    doctor_parser.add_argument(
        "--all",
        action="store_true",
        dest="check_all",
        help="Check all dependencies (default: only those needed by your workflows)",
    )
    config_parser = subparsers.add_parser(
        "config",
        help="Create/show/edit config.toml and run doctor",
    )
    config_sub = config_parser.add_subparsers(dest="config_action", metavar="COMMAND")
    config_sub.add_parser("show", help="Print config.toml and run doctor (default)")
    config_sub.add_parser("edit", help="Open config.toml in $EDITOR")

    triggers_parser = subparsers.add_parser(
        "triggers",
        help="Inspect and manage triggers",
    )
    triggers_sub = triggers_parser.add_subparsers(dest="triggers_action", metavar="COMMAND")
    triggers_sub.add_parser("list", help="List all triggers in triggers.d/")
    triggers_show = triggers_sub.add_parser("show", help="Print a trigger's YAML")
    triggers_show.add_argument("name", help="Trigger name (file stem in triggers.d/)")
    triggers_validate = triggers_sub.add_parser("validate", help="Validate a trigger YAML")
    triggers_validate.add_argument("name", help="Trigger name (file stem in triggers.d/)")
    triggers_delete = triggers_sub.add_parser("delete", help="Delete a trigger YAML file")
    triggers_delete.add_argument("name", help="Trigger name (file stem in triggers.d/)")
    triggers_delete.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    triggers_sub.add_parser("examples", help="Print example trigger YAML templates")
    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help="List and remove cached intermediate artifacts",
    )
    cleanup_parser.add_argument(
        "--source-id",
        help="Delete artifacts for one specific source id only",
    )
    cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    cleanup_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    cleanup_parser.add_argument(
        "--artifacts-only",
        action="store_true",
        help="Delete intermediate processing artifacts only (keep transcript/summary files)",
    )
    cleanup_parser.add_argument(
        "--finished-only",
        action="store_true",
        help="Delete finished output artifacts so they no longer appear in `solux serve`",
    )
    cleanup_parser.add_argument(
        "--older-than-days",
        type=int,
        help="With --finished-only, delete only outputs older than N days",
    )
    cleanup_parser.add_argument(
        "--jobs",
        action="store_true",
        help="Cleanup queue job records (done/failed/dead_letter by default)",
    )
    cleanup_parser.add_argument(
        "--jobs-stale-only",
        action="store_true",
        help="With --jobs, remove only jobs whose source_id no longer exists",
    )
    cleanup_parser.add_argument(
        "--jobs-all-statuses",
        action="store_true",
        help="With --jobs, include pending/processing jobs too (default removes terminal statuses only)",
    )
    log_parser = subparsers.add_parser(
        "log",
        help="Monitor queue status and worker logs (read-only)",
    )
    log_parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between queue polls when idle (default: 2.0)",
    )
    log_parser.add_argument(
        "--no-history",
        action="store_true",
        help="Do not print recent worker.log lines on startup",
    )
    serve_parser = subparsers.add_parser(
        "serve",
        help="Serve a local web UI for browsing processed outputs",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind (default: 8765)",
    )

    retry_parser = subparsers.add_parser(
        "retry",
        help="Reset failed jobs back to pending so they will be retried",
    )
    retry_parser.add_argument(
        "--job-id",
        dest="job_ids",
        action="append",
        default=None,
        metavar="JOB_ID",
        help="Retry only this job id (repeatable; default: retry all failed)",
    )

    subparsers.add_parser(
        "repair",
        help="Repair the job queue by recovering from filesystem and resetting stuck jobs",
    )

    subparsers.add_parser(
        "mcp",
        help="Start MCP server (stdio transport) for AI agent integration",
    )

    worker_parser = subparsers.add_parser(
        "worker",
        help="Manage the background queue worker",
    )
    worker_parser.set_defaults(worker_action="status")
    worker_subparsers = worker_parser.add_subparsers(
        dest="worker_action",
        title="commands",
        metavar="COMMAND",
    )

    worker_start = worker_subparsers.add_parser(
        "start",
        help="Start the background worker",
    )
    worker_start.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between queue polls when idle (default: 2.0)",
    )
    worker_start.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel worker threads (default: 1)",
    )
    worker_start.add_argument(
        "--_run-loop",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    worker_start.add_argument(
        "--once",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    worker_stop = worker_subparsers.add_parser(
        "stop",
        help="Stop the background worker",
    )
    worker_stop.add_argument(
        "--force",
        action="store_true",
        help="Send SIGKILL if the worker does not stop after SIGTERM",
    )
    worker_stop.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for graceful stop before failing (default: 10)",
    )

    worker_subparsers.add_parser(
        "status",
        help="Show worker state and queue counts",
    )

    return parser
