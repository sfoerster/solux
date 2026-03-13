from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths
from .config import Config, effective_external_modules_dir
from .workflows import Context, execute_workflow, load_workflow
from .workflows.registry import build_registry

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class ProcessingResult:
    source_id: str
    source_input: str
    display_name: str
    input_audio: Path
    wav_audio: Path
    transcript_path: Path
    output_text: str
    cache_output_path: Path
    export_output_path: Path


class _ProgressLoggingHandler(logging.Handler):
    def __init__(self, progress: ProgressCallback | None) -> None:
        super().__init__()
        self._progress = progress

    def emit(self, record: logging.LogRecord) -> None:
        if self._progress is None:
            return
        self._progress(self.format(record))


def _build_logger(progress: ProgressCallback | None) -> logging.Logger:
    # Use an isolated logger instance per run to avoid handler races across worker threads.
    logger = logging.Logger("solux.workflow")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = _ProgressLoggingHandler(progress)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def execute_source_workflow(
    config: Config,
    *,
    source: str,
    workflow_name: str,
    params: dict[str, object] | None = None,
    no_cache: bool = False,
    verbose: bool = False,
    progress: ProgressCallback | None = None,
    on_step_complete: "Callable | None" = None,
) -> Context:
    source_id = paths.compute_source_id(source)
    logger = _build_logger(progress)
    runtime = {
        "no_cache": no_cache,
        "verbose": verbose,
        "progress": progress,
    }

    _strict = getattr(getattr(config, "security", None), "strict_env_vars", False)
    workflow = load_workflow(workflow_name, workflow_dir=config.workflows_dir, strict_secrets=_strict)
    registry = build_registry(external_dir=effective_external_modules_dir(config))
    ctx = Context(
        source=source,
        source_id=source_id,
        data={
            "workflow_name": workflow_name,
            "runtime": runtime,
        },
        config=config,
        logger=logger,
        params=dict(params or {}),
    )
    return execute_workflow(workflow, ctx, registry=registry, on_step_complete=on_step_complete)


def process_source(
    config: Config,
    *,
    source: str,
    mode: str,
    output_format: str,
    timestamps: bool,
    no_cache: bool,
    verbose: bool,
    progress: ProgressCallback | None = None,
    model: str | None = None,
    on_step_complete: "Callable | None" = None,
) -> ProcessingResult:
    ctx = execute_source_workflow(
        config,
        source=source,
        workflow_name="audio_summary",
        params={
            "mode": mode,
            "format": output_format,
            "timestamps": timestamps,
            "model": model,
        },
        no_cache=no_cache,
        verbose=verbose,
        progress=progress,
        on_step_complete=on_step_complete,
    )

    input_audio = Path(str(ctx.data.get("audio_input_path")))
    wav_audio = Path(str(ctx.data.get("wav_path")))
    transcript_path = Path(str(ctx.data.get("transcript_path")))
    cache_output_path = Path(str(ctx.data.get("cache_output_path")))
    export_output_path = Path(str(ctx.data.get("export_output_path")))

    return ProcessingResult(
        source_id=ctx.source_id,
        source_input=source,
        display_name=str(ctx.data.get("display_name", source)),
        input_audio=input_audio,
        wav_audio=wav_audio,
        transcript_path=transcript_path,
        output_text=str(ctx.data.get("output_text", "")),
        cache_output_path=cache_output_path,
        export_output_path=export_output_path,
    )
