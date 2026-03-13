from __future__ import annotations

from solux.artifacts import display_name_for_source, write_source_metadata
from solux.modules._helpers import as_bool, runtime_flag
from solux.modules.spec import ContextKey, Dependency, ModuleSpec
from solux.sources import resolve_source_to_audio
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    del step
    no_cache = as_bool(runtime_flag(ctx, "no_cache", False))
    verbose = as_bool(runtime_flag(ctx, "verbose", False))
    progress = runtime_flag(ctx, "progress", None)

    input_audio = resolve_source_to_audio(
        config=ctx.config,
        source=ctx.source,
        source_id=ctx.source_id,
        no_cache=no_cache,
        progress=progress,
        verbose=verbose,
    )
    display_name = display_name_for_source(
        ctx.source,
        input_audio=input_audio,
        cache_dir=ctx.config.paths.cache_dir,
        source_id=ctx.source_id,
    )
    workflow_name = str(ctx.data.get("workflow_name") or "") or None
    write_source_metadata(
        cache_dir=ctx.config.paths.cache_dir,
        source_id=ctx.source_id,
        source_input=ctx.source,
        input_audio=input_audio,
        display_name=display_name,
        workflow_name=workflow_name,
    )
    ctx.data["audio_input_path"] = str(input_audio)
    ctx.data["display_name"] = display_name
    return ctx


MODULE = ModuleSpec(
    name="source_fetch",
    version="0.2.0",
    category="input",
    description="Fetch audio from a URL or local file path.",
    handler=handle,
    aliases=("source.fetch",),
    dependencies=(
        Dependency(name="yt-dlp", kind="binary", check_cmd=("yt-dlp", "--version"), hint="pip install yt-dlp"),
    ),
    config_schema=(),
    reads=(
        ContextKey("runtime.no_cache", "Skip download cache"),
        ContextKey("runtime.verbose", "Stream download output"),
        ContextKey("runtime.progress", "Progress callback"),
    ),
    writes=(
        ContextKey("audio_input_path", "Path to the downloaded/resolved audio file"),
        ContextKey("display_name", "Human-friendly name for the source"),
    ),
    network=True,
)
