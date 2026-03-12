from __future__ import annotations

from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.summarize import call_ollama_chat
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    categories = list(step.config.get("categories", []))
    if not categories:
        raise RuntimeError("ai.llm_classify: 'categories' config is required and must be non-empty")
    input_key = str(step.config.get("input_key", "input_text"))
    output_key = str(step.config.get("output_key", "classification"))
    system_prompt = step.config.get(
        "system_prompt",
        f"Classify the following text into exactly one of these categories: {categories}. "
        "Reply with only the category name, nothing else.",
    )

    input_text = ctx.data.get(input_key)
    if input_text is None:
        raise RuntimeError(f"ai.llm_classify: missing '{input_key}' in context data")

    model = ctx.params.get("model")
    prompt = {"system": str(system_prompt), "user": str(input_text)}
    raw_response = call_ollama_chat(
        ctx.config,
        prompt,
        model=model if isinstance(model, str) else None,
    )

    response_clean = raw_response.strip()
    matched_category = None
    for cat in categories:
        if response_clean.lower() == str(cat).lower():
            matched_category = str(cat)
            break
    if matched_category is None:
        # Fallback: find any category name in the response
        for cat in categories:
            if str(cat).lower() in response_clean.lower():
                matched_category = str(cat)
                break
    if matched_category is None:
        matched_category = response_clean

    ctx.data[output_key] = matched_category
    ctx.logger.info("llm_classify: classified as %r", matched_category)
    return ctx


MODULE = ModuleSpec(
    name="llm_classify",
    version="0.1.0",
    category="ai",
    description="Classify text into one of a set of categories using a local LLM via Ollama.",
    handler=handle,
    aliases=("ai.classify",),
    dependencies=(Dependency(name="ollama", kind="service", hint="https://ollama.ai"),),
    config_schema=(
        ConfigField(name="categories", description="List of category strings to classify into", required=True),
        ConfigField(name="input_key", description="Context key to read input text from", default="input_text"),
        ConfigField(name="output_key", description="Context key to write classification to", default="classification"),
        ConfigField(name="system_prompt", description="Override system prompt", default=None),
    ),
    reads=(ContextKey("input_text", "Text to classify (configurable via input_key)"),),
    writes=(ContextKey("classification", "Matched category string (configurable via output_key)"),),
    network=True,
)
