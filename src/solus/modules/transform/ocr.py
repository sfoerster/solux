from __future__ import annotations

from pathlib import Path

from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "transform.ocr requires pytesseract and Pillow. "
            "Install with: pip install pytesseract Pillow  "
            "(and ensure the tesseract binary is installed)"
        ) from exc

    input_key = str(step.config.get("input_key", ""))
    output_key = str(step.config.get("output_key", "ocr_text"))
    lang = str(step.config.get("lang", "eng"))

    if input_key:
        image_path = Path(str(ctx.data.get(input_key, ""))).expanduser()
    else:
        image_path = Path(str(ctx.source)).expanduser()

    if not image_path.exists():
        raise RuntimeError(f"transform.ocr: image file not found: {image_path}")

    try:
        img = Image.open(image_path)
        ocr_text = pytesseract.image_to_string(img, lang=lang)
    except Exception as exc:
        raise RuntimeError(f"transform.ocr: OCR failed: {exc}") from exc

    display_name = str(ctx.data.get("display_name") or image_path.name)
    ctx.data[output_key] = ocr_text.strip()
    ctx.data["display_name"] = display_name
    ctx.logger.info("ocr: extracted %d chars from %s", len(ocr_text), image_path.name)
    return ctx


MODULE = ModuleSpec(
    name="ocr",
    version="0.1.0",
    category="transform",
    description="Extract text from images using Tesseract OCR.",
    handler=handle,
    aliases=("transform.ocr",),
    dependencies=(
        Dependency(
            name="tesseract",
            kind="binary",
            check_cmd=("tesseract", "--version"),
            hint="Install tesseract-ocr via your package manager",
        ),
    ),
    config_schema=(
        ConfigField(name="input_key", description="Context key for image path (default: use ctx.source)", default=""),
        ConfigField(name="output_key", description="Context key to write OCR text to", default="ocr_text"),
        ConfigField(name="lang", description="Tesseract language code", default="eng"),
    ),
    reads=(ContextKey("input_key", "Path to image file (or uses ctx.source)"),),
    writes=(
        ContextKey("ocr_text", "Extracted text (configurable via output_key)"),
        ContextKey("display_name", "Display name from image filename"),
    ),
)
