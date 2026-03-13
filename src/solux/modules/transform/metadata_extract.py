from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from solux.modules.spec import ConfigField, ContextKey, ModuleSpec
from solux.workflows.models import Context, Step


def _pdf_metadata(path: Path) -> dict:
    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        info = reader.metadata or {}
        return {
            "title": str(info.get("/Title", path.stem) or path.stem),
            "author": str(info.get("/Author", "") or ""),
            "page_count": len(reader.pages),
        }
    except Exception:
        return {"title": path.stem, "author": ""}


def handle(ctx: Context, step: Step) -> Context:
    input_key = str(step.config.get("input_key", ""))
    output_key = str(step.config.get("output_key", "file_metadata"))

    if input_key and input_key in ctx.data:
        file_path = Path(str(ctx.data[input_key])).expanduser()
    else:
        file_path = Path(str(ctx.source)).expanduser()

    metadata: dict = {}

    # Filesystem metadata
    try:
        stat = file_path.stat()
        metadata["size_bytes"] = stat.st_size
        metadata["created_at"] = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat()
        metadata["modified_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        metadata["size_bytes"] = 0
        metadata["created_at"] = ""
        metadata["modified_at"] = ""

    metadata["filename"] = file_path.name
    metadata["extension"] = file_path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(file_path))
    metadata["mime_type"] = mime or "application/octet-stream"

    # Format-specific metadata
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        pdf_meta = _pdf_metadata(file_path)
        metadata.update(pdf_meta)
    else:
        metadata["title"] = file_path.stem
        metadata["author"] = ""

    ctx.data[output_key] = metadata
    ctx.logger.info("metadata_extract: extracted metadata for %s", file_path.name)
    return ctx


MODULE = ModuleSpec(
    name="metadata_extract",
    version="0.1.0",
    category="transform",
    description="Extract metadata from a file (filesystem stats, PDF info).",
    handler=handle,
    aliases=("transform.metadata",),
    dependencies=(),
    config_schema=(
        ConfigField(name="input_key", description="Context key for file path (default: use ctx.source)", default=""),
        ConfigField(name="output_key", description="Context key to write metadata dict to", default="file_metadata"),
    ),
    reads=(ContextKey("input_key", "Path to file (or uses ctx.source)"),),
    writes=(ContextKey("file_metadata", "Dict with title, author, size_bytes, mime_type, etc."),),
)
