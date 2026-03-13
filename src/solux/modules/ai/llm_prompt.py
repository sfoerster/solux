from __future__ import annotations

from solux.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solux.summarize import call_ollama_chat
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    system_prompt = str(step.config.get("system_prompt", "You are a helpful assistant."))
    prompt_template = str(step.config.get("prompt_template", "{input_text}"))
    input_key = str(step.config.get("input_key", "input_text"))
    output_key = str(step.config.get("output_key", "llm_output"))

    input_text = ctx.data.get(input_key)
    if input_text is None:
        raise RuntimeError(f"ai.llm_prompt: missing '{input_key}' in context data")

    try:
        rendered = prompt_template.format_map(ctx.data)
    except KeyError as exc:
        raise RuntimeError(f"ai.llm_prompt: Unresolvable variable {exc} in prompt_template") from exc

    model = ctx.params.get("model")
    prompt = {"system": system_prompt, "user": rendered}
    result = call_ollama_chat(
        ctx.config,
        prompt,
        model=model if isinstance(model, str) else None,
    )

    ctx.data[output_key] = result
    ctx.data["output_text"] = result
    return ctx


MODULE = ModuleSpec(
    name="llm_prompt",
    version="0.1.0",
    category="ai",
    description="Send configurable prompt templates to a local LLM via Ollama.",
    handler=handle,
    aliases=("llm.prompt",),
    dependencies=(
        Dependency(
            name="ollama",
            kind="service",
            hint="Install Ollama from https://ollama.ai",
        ),
    ),
    config_schema=(
        ConfigField(
            name="system_prompt", description="System prompt for the LLM", default="You are a helpful assistant."
        ),
        ConfigField(
            name="prompt_template",
            description="User prompt template with {variable} placeholders",
            default="{input_text}",
        ),
        ConfigField(name="input_key", description="Context key to read input text from", default="input_text"),
        ConfigField(name="output_key", description="Context key to write LLM output to", default="llm_output"),
    ),
    reads=(ContextKey("input_text", "The input text (configurable via input_key)"),),
    writes=(
        ContextKey("llm_output", "The LLM response (configurable via output_key)"),
        ContextKey("output_text", "Copy of LLM response for generic output"),
    ),
    network=True,
)
