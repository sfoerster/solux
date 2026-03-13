from __future__ import annotations

import re

from solux.modules.spec import ConfigField, ContextKey, ModuleSpec
from solux.workflows.models import Context, Step


def _split_fixed(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        return [text]
    if overlap < 0:
        overlap = 0
    if overlap >= chunk_size:
        # Clamp overlap so the cursor always advances and never loops forever.
        overlap = chunk_size - 1
    chunks: list[str] = []
    step = chunk_size - overlap if overlap > 0 else chunk_size
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += max(1, step)
    return [c for c in chunks if c.strip()]


def _split_paragraph(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentence(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def handle(ctx: Context, step: Step) -> Context:
    input_key = str(step.config.get("input_key", "input_text"))
    output_key = str(step.config.get("output_key", "chunks"))
    method = str(step.config.get("method", "paragraph"))
    chunk_size = int(step.config.get("chunk_size", 2000))
    overlap = int(step.config.get("overlap", 200))

    text = str(ctx.data.get(input_key, "")).strip()
    if not text:
        raise RuntimeError(f"transform.text_split: missing '{input_key}' in context data")

    if method == "fixed":
        chunks = _split_fixed(text, chunk_size, overlap)
    elif method == "sentence":
        chunks = _split_sentence(text)
    else:
        chunks = _split_paragraph(text)

    ctx.data[output_key] = chunks
    ctx.logger.info("text_split: %d chunks (method=%s)", len(chunks), method)
    return ctx


MODULE = ModuleSpec(
    name="text_split",
    version="0.1.0",
    category="transform",
    description="Split text into chunks by paragraph, sentence, or fixed size.",
    handler=handle,
    aliases=("transform.split",),
    dependencies=(),
    config_schema=(
        ConfigField(name="input_key", description="Context key to read text from", default="input_text"),
        ConfigField(name="output_key", description="Context key to write chunks list to", default="chunks"),
        ConfigField(name="method", description="Split method: paragraph, sentence, or fixed", default="paragraph"),
        ConfigField(
            name="chunk_size", description="Chunk size in characters (for fixed method)", type="int", default=2000
        ),
        ConfigField(
            name="overlap",
            description="Overlap in characters between chunks (for fixed method)",
            type="int",
            default=200,
        ),
    ),
    reads=(ContextKey("input_text", "Text to split (configurable via input_key)"),),
    writes=(ContextKey("chunks", "List of text chunks (configurable via output_key)"),),
)
