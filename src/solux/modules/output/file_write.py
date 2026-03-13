from __future__ import annotations

from solux import paths
from solux.artifacts import slugify
from solux.modules._helpers import param
from solux.modules.spec import ConfigField, ContextKey, ModuleSpec
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    input_key = str(step.config.get("input_key", "output_text"))
    output_text = str(ctx.data.get(input_key, "")).strip()
    if not output_text:
        raise RuntimeError(f"Missing {input_key} for output.file_write step")

    display_name = str(ctx.data.get("display_name") or ctx.source)
    mode = str(param(ctx, "mode", step, "output"))
    output_format = str(param(ctx, "format", step, "markdown"))

    export_output_path = paths.exported_output_path(
        cache_dir=ctx.config.paths.cache_dir,
        source_id=ctx.source_id,
        display_slug=slugify(display_name),
        mode=mode,
        output_format=output_format,
    )
    export_output_path.write_text(output_text, encoding="utf-8")

    ctx.data["export_output_path"] = str(export_output_path)
    return ctx


MODULE = ModuleSpec(
    name="file_write",
    version="0.3.0",
    category="output",
    description="Write output text to a file.",
    handler=handle,
    aliases=(),
    dependencies=(),
    config_schema=(
        ConfigField(name="input_key", description="Context key to read output text from", default="output_text"),
        ConfigField(name="mode", description="Output mode label for filename", default="output"),
        ConfigField(name="format", description="Output format (markdown, text, json)", default="markdown"),
    ),
    reads=(
        ContextKey("output_text", "The text to write (configurable via input_key)"),
        ContextKey("display_name", "Human-friendly name for filename"),
    ),
    writes=(ContextKey("export_output_path", "Path to the written output file"),),
)
