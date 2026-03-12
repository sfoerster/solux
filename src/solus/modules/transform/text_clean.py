from __future__ import annotations

import re

from solus.html_text import html_to_text
from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def _strip_html(text: str) -> str:
    return html_to_text(text)


def handle(ctx: Context, step: Step) -> Context:
    input_key = str(step.config.get("input_key", "input_text"))
    output_key = str(step.config.get("output_key", "cleaned_text"))
    do_strip_html = bool(step.config.get("strip_html", True))
    normalize_whitespace = bool(step.config.get("normalize_whitespace", True))
    max_chars = int(step.config.get("max_chars", 0))

    text = str(ctx.data.get(input_key, ""))
    if not text and input_key == "input_text":
        # Try fallback to output_text or webpage_text
        text = str(ctx.data.get("output_text") or ctx.data.get("webpage_text", ""))

    if do_strip_html:
        text = _strip_html(text)

    if normalize_whitespace:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

    if max_chars > 0:
        text = text[:max_chars]

    ctx.data[output_key] = text
    ctx.logger.info("text_clean: cleaned text, %d chars", len(text))
    return ctx


MODULE = ModuleSpec(
    name="text_clean",
    version="0.1.0",
    category="transform",
    description="Clean text by stripping HTML, normalizing whitespace, and truncating.",
    handler=handle,
    aliases=("transform.clean",),
    dependencies=(),
    config_schema=(
        ConfigField(name="input_key", description="Context key to read text from", default="input_text"),
        ConfigField(name="output_key", description="Context key to write cleaned text to", default="cleaned_text"),
        ConfigField(name="strip_html", description="Strip HTML tags", type="bool", default=True),
        ConfigField(name="normalize_whitespace", description="Collapse whitespace", type="bool", default=True),
        ConfigField(name="max_chars", description="Truncate to N chars (0=unlimited)", type="int", default=0),
    ),
    reads=(ContextKey("input_text", "Text to clean (configurable via input_key)"),),
    writes=(ContextKey("cleaned_text", "Cleaned text (configurable via output_key)"),),
)
