from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def _safe_filename(name: str) -> str:
    import re

    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name[:200] or "note"


def handle(ctx: Context, step: Step) -> Context:
    vault_raw = str(step.config.get("vault_path", "")).strip()
    if not vault_raw:
        raise RuntimeError("output.obsidian_vault: 'vault_path' is required")
    vault_path = Path(vault_raw).expanduser()

    folder = str(step.config.get("folder", "solus"))
    input_key = str(step.config.get("input_key", "output_text"))
    filename_key = str(step.config.get("filename_key", "display_name"))
    tags = list(step.config.get("tags", []))
    overwrite = bool(step.config.get("overwrite", False))

    body = str(ctx.data.get(input_key, ""))
    raw_name = str(ctx.data.get(filename_key) or ctx.source)
    safe_name = _safe_filename(raw_name)
    if not safe_name.endswith(".md"):
        safe_name += ".md"

    note_dir = vault_path / folder
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / safe_name

    if note_path.exists() and not overwrite:
        ctx.logger.warning("obsidian_vault: note already exists, skipping: %s", note_path)
        ctx.data["obsidian_note_path"] = str(note_path)
        return ctx

    created = datetime.now(timezone.utc).isoformat()
    tag_str = ""
    if tags:
        tag_list = "\n".join(f"  - {t}" for t in tags)
        tag_str = f"tags:\n{tag_list}\n"

    frontmatter = f"---\nsource: {ctx.source}\ncreated: {created}\n{tag_str}---\n\n"
    note_path.write_text(frontmatter + body, encoding="utf-8")

    ctx.data["obsidian_note_path"] = str(note_path)
    ctx.logger.info("obsidian_vault: wrote note to %s", note_path)
    return ctx


MODULE = ModuleSpec(
    name="obsidian_vault",
    version="0.1.0",
    category="output",
    description="Write a note to an Obsidian vault with YAML frontmatter.",
    handler=handle,
    aliases=("output.obsidian",),
    dependencies=(),
    config_schema=(
        ConfigField(name="vault_path", description="Path to Obsidian vault root", required=True),
        ConfigField(name="folder", description="Subdirectory within vault", default="solus"),
        ConfigField(name="input_key", description="Context key for note body", default="output_text"),
        ConfigField(name="filename_key", description="Context key for note filename", default="display_name"),
        ConfigField(name="tags", description="List of tags to add to frontmatter"),
        ConfigField(name="overwrite", description="Overwrite existing notes", type="bool", default=False),
    ),
    reads=(
        ContextKey("output_text", "Note body (configurable via input_key)"),
        ContextKey("display_name", "Note filename (configurable via filename_key)"),
    ),
    writes=(ContextKey("obsidian_note_path", "Absolute path to the written note file"),),
    safety="trusted_only",
)
