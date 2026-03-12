from __future__ import annotations

import requests

from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    input_key = str(step.config.get("input_key", "input_text"))
    output_key = str(step.config.get("output_key", "embedding"))
    model_override = step.config.get("model", None)

    input_text = ctx.data.get(input_key)
    if input_text is None:
        raise RuntimeError(f"ai.embeddings: missing '{input_key}' in context data")

    model = model_override or ctx.params.get("model") or ctx.config.ollama.model
    url = f"{ctx.config.ollama.base_url}/api/embeddings"

    ctx.logger.info("embeddings: calling %s with model=%s", url, model)
    try:
        resp = requests.post(
            url,
            json={"model": str(model), "prompt": str(input_text)},
            timeout=60,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"ai.embeddings: failed to call Ollama embeddings API: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("ai.embeddings: Ollama returned non-JSON response") from exc

    embedding = data.get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError(f"ai.embeddings: unexpected response format: {data}")

    ctx.data[output_key] = embedding
    ctx.logger.info("embeddings: got embedding of dimension %d", len(embedding))
    return ctx


MODULE = ModuleSpec(
    name="embeddings",
    version="0.1.0",
    category="ai",
    description="Generate text embeddings using Ollama's /api/embeddings endpoint.",
    handler=handle,
    dependencies=(Dependency(name="ollama", kind="service", hint="https://ollama.ai"),),
    config_schema=(
        ConfigField(name="input_key", description="Context key to read input text from", default="input_text"),
        ConfigField(name="output_key", description="Context key to write embedding to", default="embedding"),
        ConfigField(name="model", description="Embedding model name (default: from config)", default=None),
    ),
    reads=(ContextKey("input_text", "Text to embed (configurable via input_key)"),),
    writes=(ContextKey("embedding", "List of floats representing the embedding vector (configurable via output_key)"),),
    network=True,
)
