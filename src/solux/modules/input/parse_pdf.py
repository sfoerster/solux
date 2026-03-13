from __future__ import annotations

from pathlib import Path

from solux.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    try:
        import pypdf
    except ImportError as exc:
        raise RuntimeError(
            "input.parse_pdf requires pypdf. Install with: pip install 'solux[pdf]' or pip install pypdf>=4.0"
        ) from exc

    output_key = str(step.config.get("output_key", "pdf_text"))
    pages_cfg = step.config.get("pages", None)

    source_path = Path(ctx.source).expanduser()
    if not source_path.exists():
        raise RuntimeError(f"input.parse_pdf: source file not found: {source_path}")

    ctx.logger.info("parse_pdf: reading %s", source_path)
    try:
        reader = pypdf.PdfReader(str(source_path))
    except Exception as exc:
        raise RuntimeError(f"input.parse_pdf: failed to open PDF: {exc}") from exc

    total_pages = len(reader.pages)
    if pages_cfg is not None:
        if isinstance(pages_cfg, (list, tuple)):
            page_indices = [int(p) for p in pages_cfg]
        else:
            page_indices = list(range(int(pages_cfg)))
    else:
        page_indices = list(range(total_pages))

    text_parts: list[str] = []
    for idx in page_indices:
        if 0 <= idx < total_pages:
            try:
                text_parts.append(reader.pages[idx].extract_text() or "")
            except Exception:
                text_parts.append("")

    pdf_text = "\n".join(text_parts)
    ctx.data[output_key] = pdf_text
    ctx.data["display_name"] = source_path.name
    ctx.logger.info("parse_pdf: extracted %d chars from %d page(s)", len(pdf_text), len(page_indices))
    return ctx


MODULE = ModuleSpec(
    name="parse_pdf",
    version="0.1.0",
    category="input",
    description="Extract text from a PDF file using pypdf (install: pip install 'solux[pdf]').",
    handler=handle,
    dependencies=(Dependency(name="pypdf", kind="binary", hint="pip install 'solux[pdf]'"),),
    config_schema=(
        ConfigField(name="output_key", description="Context key to write extracted text to", default="pdf_text"),
        ConfigField(name="pages", description="Page indices to extract (None = all pages)", default=None),
    ),
    reads=(),
    writes=(
        ContextKey("pdf_text", "Extracted text from PDF (configurable via output_key)"),
        ContextKey("display_name", "PDF filename"),
    ),
)
