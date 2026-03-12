from __future__ import annotations

from solus import paths
from solus.artifacts import format_transcript_output, slugify
from solus.modules._helpers import as_bool, param, runtime_flag
from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.summarize import summarize_transcript
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    mode = str(param(ctx, "mode", step, "full"))
    output_format = str(param(ctx, "format", step, "markdown"))
    timestamps = as_bool(param(ctx, "timestamps", step, False))
    no_cache = as_bool(runtime_flag(ctx, "no_cache", False))
    progress = runtime_flag(ctx, "progress", None)
    model = ctx.params.get("model")
    input_key = str(step.config.get("input_key", "transcript_text"))
    transcript = str(ctx.data.get(input_key, "")).strip()
    if not transcript:
        raise RuntimeError(f"Missing {input_key} for ai.llm_summarize step")

    if mode == "transcript":
        output_text = format_transcript_output(transcript, output_format)
        cache_output_path = paths.summary_path(
            cache_dir=ctx.config.paths.cache_dir,
            source_id=ctx.source_id,
            mode="transcript",
            output_format=output_format,
        )
        cache_output_path.write_text(output_text, encoding="utf-8")
    else:
        cache_output_path = paths.summary_path(
            cache_dir=ctx.config.paths.cache_dir,
            source_id=ctx.source_id,
            mode=mode,
            output_format=output_format,
        )
        if cache_output_path.exists() and not no_cache:
            output_text = cache_output_path.read_text(encoding="utf-8")
        else:
            output_text = summarize_transcript(
                config=ctx.config,
                transcript=transcript,
                mode=mode,
                timestamps=timestamps,
                output_format=output_format,
                progress=progress,
                model=model if isinstance(model, str) else None,
            )
            cache_output_path.write_text(output_text, encoding="utf-8")

    display_name = str(ctx.data.get("display_name") or ctx.source)
    export_output_path = paths.exported_output_path(
        cache_dir=ctx.config.paths.cache_dir,
        source_id=ctx.source_id,
        display_slug=slugify(display_name),
        mode=mode,
        output_format=output_format,
    )
    export_output_path.write_text(output_text, encoding="utf-8")

    ctx.data["summary_text"] = output_text
    ctx.data["output_text"] = output_text
    ctx.data["mode"] = mode
    ctx.data["format"] = output_format
    ctx.data["cache_output_path"] = str(cache_output_path)
    ctx.data["export_output_path"] = str(export_output_path)
    return ctx


MODULE = ModuleSpec(
    name="llm_summarize",
    version="0.2.0",
    category="ai",
    description="Summarize transcripts using a local LLM via Ollama.",
    handler=handle,
    aliases=("llm.summarize",),
    dependencies=(
        Dependency(
            name="ollama",
            kind="service",
            hint="Install Ollama from https://ollama.ai",
        ),
    ),
    config_schema=(
        ConfigField(name="input_key", description="Context key to read input text from", default="transcript_text"),
        ConfigField(name="mode", description="Summary mode", default="full"),
        ConfigField(name="format", description="Output format", default="markdown"),
        ConfigField(name="timestamps", description="Include timestamps", type="bool", default=False),
    ),
    reads=(ContextKey("transcript_text", "The input text to summarize (configurable via input_key)"),),
    writes=(
        ContextKey("summary_text", "The generated summary text"),
        ContextKey("output_text", "Copy of summary_text for generic output"),
        ContextKey("mode", "The summary mode used"),
        ContextKey("format", "The output format used"),
        ContextKey("cache_output_path", "Path to the cached summary file"),
        ContextKey("export_output_path", "Path to the exported summary file"),
    ),
    network=True,
)
