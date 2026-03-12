from __future__ import annotations

import fnmatch
from pathlib import Path

from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    watch_path = Path(str(step.config.get("path", ""))).expanduser()
    if not step.config.get("path"):
        raise RuntimeError("input.folder_watch: 'path' config is required")
    pattern = str(step.config.get("pattern", "*"))
    output_key = str(step.config.get("output_key", "found_files"))

    if not watch_path.exists():
        ctx.logger.warning("folder_watch: path does not exist: %s", watch_path)
        ctx.data[output_key] = []
        return ctx

    matched: list[Path] = []
    for item in watch_path.iterdir():
        if not item.is_file():
            continue
        if fnmatch.fnmatch(item.name, pattern):
            matched.append(item)

    matched.sort(key=lambda p: p.stat().st_mtime)
    file_paths = [str(p) for p in matched]
    ctx.data[output_key] = file_paths
    ctx.logger.info("folder_watch: found %d file(s) in %s matching %r", len(file_paths), watch_path, pattern)
    return ctx


MODULE = ModuleSpec(
    name="folder_watch",
    version="0.1.0",
    category="input",
    description="Snapshot a folder for files matching a pattern; returns list of file paths sorted by mtime.",
    handler=handle,
    config_schema=(
        ConfigField(name="path", description="Directory path to scan", required=True),
        ConfigField(name="pattern", description="Glob pattern to match filenames", default="*"),
        ConfigField(name="output_key", description="Context key to write file paths list to", default="found_files"),
    ),
    reads=(),
    writes=(ContextKey("found_files", "List of matching file path strings, sorted by mtime"),),
)
