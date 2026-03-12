from __future__ import annotations

import requests

from solus.modules._helpers import interpolate_env
from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    node_url = interpolate_env(str(step.config.get("node_url", ""))).rstrip("/")
    auth_token = interpolate_env(str(step.config.get("auth_token", "")))
    workflow_name = str(step.config.get("workflow_name", ""))
    input_key = str(step.config.get("input_key", "output_text"))
    verify_ssl = bool(step.config.get("verify_ssl", True))
    raise_on_error = bool(step.config.get("raise_on_error", True))

    if not node_url:
        raise RuntimeError("output.vinsium_node: 'node_url' is required")
    if not workflow_name:
        raise RuntimeError("output.vinsium_node: 'workflow_name' is required")

    payload_text = str(ctx.data.get(input_key, ""))
    payload = {
        "source": ctx.source,
        "source_id": ctx.source_id,
        "text": payload_text,
        "params": ctx.params,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    endpoint = f"{node_url}/api/trigger/{workflow_name}"
    try:
        resp = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=30,
            verify=verify_ssl,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"output.vinsium_node: request to {endpoint} failed: {exc}") from exc

    job_id = ""
    try:
        data = resp.json()
        job_id = str(data.get("job_id", ""))
    except Exception:
        ctx.logger.warning("output.vinsium_node: could not parse response JSON (status=%d)", resp.status_code)

    ctx.data["vinsium_response_status"] = resp.status_code
    ctx.data["vinsium_job_id"] = job_id
    ctx.logger.info("vinsium_node: POST %s -> %d (job_id=%s)", endpoint, resp.status_code, job_id)
    if raise_on_error and not resp.ok:
        raise RuntimeError(f"output.vinsium_node: server returned {resp.status_code}: {resp.text[:200]}")
    return ctx


MODULE = ModuleSpec(
    name="vinsium_node",
    version="0.1.0",
    category="output",
    description="POST workflow result to a remote Vinsium-hosted Solus node.",
    handler=handle,
    aliases=("output.vinsium",),
    dependencies=(),
    config_schema=(
        ConfigField(name="node_url", description="Base URL of remote Solus node", required=True),
        ConfigField(name="auth_token", description="Bearer token for authentication (supports ${env:VAR})"),
        ConfigField(name="workflow_name", description="Target workflow name on remote node", required=True),
        ConfigField(name="input_key", description="Context key for payload text", default="output_text"),
        ConfigField(name="verify_ssl", description="Verify SSL certificate", type="bool", default=True),
        ConfigField(name="raise_on_error", description="Raise on non-2xx response", type="bool", default=True),
    ),
    reads=(ContextKey("output_text", "Payload text to send (configurable via input_key)"),),
    writes=(
        ContextKey("vinsium_response_status", "HTTP status code from remote node"),
        ContextKey("vinsium_job_id", "Job ID returned by remote node"),
    ),
    safety="trusted_only",
    network=True,
)
