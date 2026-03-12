from __future__ import annotations

import json

from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.summarize import call_ollama_chat
from solus.workflows.models import Context, Step

_SCALE_PROMPTS = {
    "pos_neg_neu": (
        "Analyze the sentiment of the following text. "
        "Reply with a JSON object with keys: label (one of: positive, negative, neutral), "
        "score (float 0-1), explanation (brief). "
        "Reply ONLY with valid JSON."
    ),
    "five_point": (
        "Analyze the sentiment of the following text on a 5-point scale. "
        "Reply with a JSON object with keys: label (one of: very_positive, positive, neutral, "
        "negative, very_negative), score (float 0-1 where 1=very_positive), explanation (brief). "
        "Reply ONLY with valid JSON."
    ),
    "detailed": (
        "Perform a detailed sentiment analysis of the following text. "
        "Reply with a JSON object with keys: label (string), score (float 0-1), "
        "emotions (list of strings), explanation (1-2 sentences). "
        "Reply ONLY with valid JSON."
    ),
}


def handle(ctx: Context, step: Step) -> Context:
    input_key = str(step.config.get("input_key", "input_text"))
    output_key = str(step.config.get("output_key", "sentiment"))
    scale = str(step.config.get("scale", "pos_neg_neu"))

    text = str(ctx.data.get(input_key, "")).strip()
    if not text:
        raise RuntimeError(f"ai.llm_sentiment: missing '{input_key}' in context data")

    system_prompt = _SCALE_PROMPTS.get(scale, _SCALE_PROMPTS["pos_neg_neu"])
    model = ctx.params.get("model")

    raw = call_ollama_chat(
        ctx.config,
        {"system": system_prompt, "user": text},
        model=model if isinstance(model, str) else None,
    )

    # Parse JSON from response
    result: dict = {}
    try:
        # Find JSON block in response
        import re

        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            result = json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        pass

    if not result:
        result = {"label": raw.strip(), "score": 0.5, "explanation": ""}

    ctx.data[output_key] = result
    ctx.logger.info("llm_sentiment: label=%r score=%s", result.get("label"), result.get("score"))
    return ctx


MODULE = ModuleSpec(
    name="llm_sentiment",
    version="0.1.0",
    category="ai",
    description="Analyze sentiment of text using a local LLM via Ollama.",
    handler=handle,
    aliases=("ai.sentiment",),
    dependencies=(Dependency(name="ollama", kind="service", hint="https://ollama.ai"),),
    config_schema=(
        ConfigField(name="input_key", description="Context key to read text from", default="input_text"),
        ConfigField(name="output_key", description="Context key to write sentiment dict to", default="sentiment"),
        ConfigField(
            name="scale", description="Sentiment scale: pos_neg_neu, five_point, or detailed", default="pos_neg_neu"
        ),
    ),
    reads=(ContextKey("input_text", "Text to analyze (configurable via input_key)"),),
    writes=(ContextKey("sentiment", "Dict with label, score, explanation (configurable via output_key)"),),
    network=True,
)
