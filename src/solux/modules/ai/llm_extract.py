from __future__ import annotations

import json
import re

from solux.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solux.summarize import call_ollama_chat
from solux.workflows.models import Context, Step


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def handle(ctx: Context, step: Step) -> Context:
    fields = list(step.config.get("fields", []))
    if not fields:
        raise RuntimeError("ai.llm_extract: 'fields' config is required and must be non-empty")
    input_key = str(step.config.get("input_key", "input_text"))
    output_key = str(step.config.get("output_key", "extracted"))
    fields_list = ", ".join(f'"{f}"' for f in fields)
    system_prompt = step.config.get(
        "system_prompt",
        f"Extract the following fields from the text and return them as a JSON object: {fields_list}. "
        "Return only a JSON object, nothing else.",
    )

    input_text = ctx.data.get(input_key)
    if input_text is None:
        raise RuntimeError(f"ai.llm_extract: missing '{input_key}' in context data")

    model = ctx.params.get("model")
    prompt = {"system": str(system_prompt), "user": str(input_text)}
    raw_response = call_ollama_chat(
        ctx.config,
        prompt,
        model=model if isinstance(model, str) else None,
    )

    cleaned = _strip_code_fences(raw_response)
    try:
        extracted = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"ai.llm_extract: LLM did not return valid JSON: {exc}. Response: {raw_response[:200]}"
        ) from exc

    if not isinstance(extracted, dict):
        raise RuntimeError(f"ai.llm_extract: expected JSON object, got {type(extracted).__name__}")

    ctx.data[output_key] = extracted
    ctx.logger.info("llm_extract: extracted %d field(s)", len(extracted))
    return ctx


MODULE = ModuleSpec(
    name="llm_extract",
    version="0.1.0",
    category="ai",
    description="Extract structured fields from text using a local LLM via Ollama; returns a JSON dict.",
    handler=handle,
    aliases=("ai.extract",),
    dependencies=(Dependency(name="ollama", kind="service", hint="https://ollama.ai"),),
    config_schema=(
        ConfigField(name="fields", description="List of field names to extract", required=True),
        ConfigField(name="input_key", description="Context key to read input text from", default="input_text"),
        ConfigField(name="output_key", description="Context key to write extracted dict to", default="extracted"),
        ConfigField(name="system_prompt", description="Override system prompt", default=None),
    ),
    reads=(ContextKey("input_text", "Text to extract from (configurable via input_key)"),),
    writes=(ContextKey("extracted", "Dict of extracted field values (configurable via output_key)"),),
    network=True,
)
