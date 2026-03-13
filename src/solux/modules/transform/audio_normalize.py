from __future__ import annotations

from pathlib import Path

from solux.audio import normalize_audio_to_wav
from solux.modules._helpers import as_bool, runtime_flag
from solux.modules.spec import ContextKey, Dependency, ModuleSpec
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    del step
    input_path = Path(str(ctx.data["audio_input_path"]))
    no_cache = as_bool(runtime_flag(ctx, "no_cache", False))
    verbose = as_bool(runtime_flag(ctx, "verbose", False))
    progress = runtime_flag(ctx, "progress", None)

    wav_path = normalize_audio_to_wav(
        config=ctx.config,
        input_audio=input_path,
        source_id=ctx.source_id,
        no_cache=no_cache,
        progress=progress,
        verbose=verbose,
    )
    ctx.data["wav_path"] = str(wav_path)
    return ctx


MODULE = ModuleSpec(
    name="audio_normalize",
    version="0.2.0",
    category="transform",
    description="Normalize audio to 16 kHz mono WAV using ffmpeg.",
    handler=handle,
    aliases=("audio.normalize",),
    dependencies=(Dependency(name="ffmpeg", kind="binary", check_cmd=("ffmpeg", "-version"), hint="Install ffmpeg"),),
    reads=(ContextKey("audio_input_path", "Path to the raw input audio file"),),
    writes=(ContextKey("wav_path", "Path to the normalized WAV file"),),
)
