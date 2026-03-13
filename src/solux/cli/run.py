from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from ..config import ConfigError, default_workflow_name, effective_external_modules_dir, load_config
from ..pipeline import execute_source_workflow, process_source
from ..workflows.loader import WorkflowLoadError, load_workflow
from ..workflows.models import Context, Workflow
from ..workflows.registry import StepRegistry
from ..workflows.validation import ValidationResult, validate_workflow


def _write_or_print(content: str, output_path: Path | None) -> None:
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(f"Wrote output to {output_path}")
    else:
        print(content)


def _progress_logger() -> Callable[[str], None]:
    def _log(message: str) -> None:
        print(f"[progress] {message}", file=sys.stderr, flush=True)

    return _log


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


def _context_output_text(ctx: Context) -> str:
    data = ctx.data
    if isinstance(data.get("output_text"), str):
        return str(data["output_text"])
    if isinstance(data.get("summary_text"), str):
        return str(data["summary_text"])
    if isinstance(data.get("transcript_text"), str):
        return str(data["transcript_text"])
    return ""


def _audio_failure_hint(error: Exception, workflow_name: str) -> str | None:
    if workflow_name != "audio_summary":
        return None

    message = str(error).lower()
    audio_keywords = ("yt-dlp", "ffmpeg", "whisper", "ollama", "/api/chat", "/api/tags")
    if not any(keyword in message for keyword in audio_keywords):
        return None

    return (
        "Hint: `audio_summary` depends on yt-dlp, ffmpeg, whisper-cli (+model), and Ollama.\n"
        "      Run: solux doctor --workflow audio_summary\n"
        '      Fast first run without audio stack: solux run --workflow webpage_summary "https://example.com"'
    )


def _generic_failure_hint(error: Exception) -> str | None:
    message = str(error).lower()
    if "connection refused" in message or "ollama" in message:
        return "Hint: Is Ollama running?  Start it with: ollama serve"
    if "config" in message and ("not found" in message or "missing" in message):
        return "Hint: Run `solux init` to set up config and workflows."
    return None


def _step_progress_callback() -> Callable:
    """Return an on_step_complete callback matching engine signature (ctx, step_name, step_num, total)."""

    def _on_step(ctx: Context, step_name: str, step_num: int, total_steps: int) -> None:
        timings = ctx.data.get("step_timings", [])
        step_type = ""
        elapsed_s = 0.0
        if timings and len(timings) >= step_num:
            entry = timings[step_num - 1]
            step_type = entry.get("type", "")
            elapsed_s = entry.get("duration_ms", 0) / 1000.0
        label = f"({step_type}) " if step_type else ""
        print(
            f"[{step_num}/{total_steps}] {step_name} {label}done ({elapsed_s:.1f}s)",
            file=sys.stderr,
            flush=True,
        )

    return _on_step


def _print_dry_run(
    workflow: Workflow,
    result: ValidationResult,
    registry: StepRegistry | None = None,
) -> None:
    from ..workflows.registry import global_registry

    active_registry = registry if registry is not None else global_registry
    print(f"Workflow: {workflow.name}")
    if workflow.description:
        print(f"  {workflow.description}")
    print()
    print("Steps:")
    total = len(workflow.steps)
    for i, step in enumerate(workflow.steps, 1):
        spec = active_registry.get_spec(step.type)
        step_label = f"  {i}. {step.name}  [{step.type}]"
        print(step_label)
        if spec:
            read_keys = [ck.key for ck in spec.reads]
            write_keys = [ck.key for ck in spec.writes]
            if read_keys:
                print(f"     reads:  {', '.join(read_keys)}")
            if write_keys:
                print(f"     writes: {', '.join(write_keys)}")
        if i < total:
            print("       |")
            print("       v")

    print()

    for issue in result.issues:
        tag = "ERROR" if issue.level == "error" else "WARNING"
        print(f"  [{tag}] step '{issue.step_name}': {issue.message}")
    if result.issues:
        print()

    if result.valid:
        print("Validation: OK")
    else:
        error_count = 0
        for issue in result.issues:
            if issue.level == "error":
                error_count += 1
        print(f"Validation: FAILED ({error_count} error(s))")


def cmd_run(args: argparse.Namespace) -> int:
    if args.dry_run:
        from ..workflows.registry import build_registry

        try:
            config = load_config()
        except ConfigError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1
        _strict = getattr(getattr(config, "security", None), "strict_env_vars", False)
        try:
            workflow = load_workflow(args.workflow, workflow_dir=config.workflows_dir, strict_secrets=_strict)
        except WorkflowLoadError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        registry = build_registry(external_dir=effective_external_modules_dir(config))
        security_mode = str(getattr(getattr(config, "security", None), "mode", "trusted")).lower()
        validation = validate_workflow(workflow, registry=registry, security_mode=security_mode)
        _print_dry_run(workflow, validation, registry=registry)
        return 0 if validation.valid else 1

    progress = None if args.quiet_progress else _progress_logger()
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if progress:
        progress(f"Loaded config from {config.config_path}")

    params = _build_run_params(args)
    workflow_name = str(args.workflow or default_workflow_name(config))

    on_step = None if args.quiet_progress else _step_progress_callback()

    try:
        if workflow_name == "audio_summary":
            processing_result = process_source(
                config=config,
                source=args.source,
                mode=args.mode,
                output_format=args.format,
                timestamps=args.timestamps,
                no_cache=args.no_cache,
                verbose=args.verbose,
                progress=progress,
                model=args.model,
                on_step_complete=on_step,
            )
            output_text = processing_result.output_text
        else:
            ctx = execute_source_workflow(
                config=config,
                source=args.source,
                workflow_name=workflow_name,
                params=params,
                no_cache=args.no_cache,
                verbose=args.verbose,
                progress=progress,
                on_step_complete=on_step,
            )
            output_text = _context_output_text(ctx)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        hint = _audio_failure_hint(exc, workflow_name) or _generic_failure_hint(exc)
        if hint:
            print(hint, file=sys.stderr)
        return 1

    if progress:
        if args.output:
            progress(f"Writing output file: {args.output}")
        else:
            progress("Writing output to stdout")
    _write_or_print(output_text, args.output)
    if progress:
        progress("Done")
    return 0
