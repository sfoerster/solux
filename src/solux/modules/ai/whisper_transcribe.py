from __future__ import annotations

from pathlib import Path

from solux.modules._helpers import as_bool, runtime_flag
from solux.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solux.transcribe import transcribe_audio
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    output_key = str(step.config.get("output_key", "transcript"))
    wav_path = Path(str(ctx.data["wav_path"]))
    no_cache = as_bool(runtime_flag(ctx, "no_cache", False))
    verbose = as_bool(runtime_flag(ctx, "verbose", False))
    progress = runtime_flag(ctx, "progress", None)

    transcript_path = transcribe_audio(
        config=ctx.config,
        wav_path=wav_path,
        source_id=ctx.source_id,
        no_cache=no_cache,
        progress=progress,
        verbose=verbose,
    )
    transcript_text = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
    if not transcript_text:
        raise RuntimeError(f"ai.whisper_transcribe: transcript file is empty: {transcript_path}")

    ctx.data["transcript_path"] = str(transcript_path)
    ctx.data["transcript_text"] = transcript_text
    ctx.data[f"{output_key}_path"] = str(transcript_path)
    ctx.data[f"{output_key}_text"] = transcript_text
    return ctx


MODULE = ModuleSpec(
    name="whisper_transcribe",
    version="0.2.0",
    category="ai",
    description="Transcribe audio to text using whisper.cpp.",
    handler=handle,
    aliases=("whisper.transcribe",),
    dependencies=(
        Dependency(
            name="whisper-cli",
            kind="binary",
            check_cmd=("whisper-cli", "--help"),
            hint="Build whisper.cpp and set whisper.cli_path in config.toml",
        ),
    ),
    config_schema=(
        ConfigField(name="output_key", description="Context key prefix for transcript output", default="transcript"),
    ),
    reads=(ContextKey("wav_path", "Path to the normalized WAV file"),),
    writes=(
        ContextKey("transcript_path", "Path to the transcript text file"),
        ContextKey("transcript_text", "The transcript text content"),
    ),
)
