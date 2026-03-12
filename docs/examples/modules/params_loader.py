# Custom module: transform.params_loader
#
# Bridges webhook/forwarded params into ctx.data for downstream modules.
#
# Use cases:
# - Node B ingest workflow reads ctx.params["text"] from output.vinsium_node.
# - Node A callback workflow reads ctx.params["result"] from output.webhook.
#
# Standard modules (text_split, llm_summarize, file_write, etc.) read from
# ctx.data, so this module copies a selected params key into ctx.data.
#
# It also exposes NODE_A_CALLBACK_URL in ctx.data["node_a_callback_url"] so
# workflows can use `when:` conditions to skip callback steps when unset.
#
# Usage in embed_and_store.yaml:
#   - name: load_forwarded_text
#     type: transform.params_loader
#     config:
#       param_key: text
#       output_key: cleaned_text

import os

from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    param_key = str(step.config.get("param_key", "text"))
    output_key = str(step.config.get("output_key", "cleaned_text"))
    value = ctx.params.get(param_key, "")
    if value in ("", None):
        ctx.logger.warning(
            "params_loader: ctx.params[%r] is empty.",
            param_key,
        )
    ctx.data[output_key] = str(value or "")
    ctx.data["node_a_callback_url"] = os.environ.get("NODE_A_CALLBACK_URL", "").strip()
    ctx.logger.info(
        "params_loader: loaded %d chars from params[%r] into ctx.data[%r]",
        len(str(value or "")),
        param_key,
        output_key,
    )
    return ctx


MODULE = ModuleSpec(
    name="params_loader",
    version="0.1.0",
    category="transform",
    description=(
        "Copy a selected key from ctx.params into ctx.data for downstream steps. "
        "Also exposes NODE_A_CALLBACK_URL for callback gating."
    ),
    handler=handle,
    config_schema=(
        ConfigField(
            name="param_key",
            description="ctx.params key to read from",
            default="text",
        ),
        ConfigField(
            name="output_key",
            description="Context key to write the value into",
            default="cleaned_text",
        ),
    ),
    reads=(),
    writes=(
        ContextKey("cleaned_text", "Forwarded text from ctx.params (default output key)"),
        ContextKey("summary_text", "Callback summary from ctx.params when output_key=summary_text"),
        ContextKey("node_a_callback_url", "NODE_A_CALLBACK_URL from environment for when: conditions"),
    ),
    safety="safe",
    network=False,
)
