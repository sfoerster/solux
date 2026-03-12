from __future__ import annotations

from urllib.parse import urlparse

import requests

from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.workflows.models import Context, Step


def _redacted_url_for_log(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "[redacted]"
    host = parsed.netloc.split("@")[-1]
    return f"{parsed.scheme}://{host}"


def handle(ctx: Context, step: Step) -> Context:
    url = str(step.config.get("url", ""))
    if not url:
        raise RuntimeError("output.webhook: 'url' config is required")
    method = str(step.config.get("method", "POST")).upper()
    input_key = str(step.config.get("input_key", "output_text"))
    headers = dict(step.config.get("headers", {}))
    wrap_key = step.config.get("wrap_key", None)
    raise_on_error = bool(step.config.get("raise_on_error", True))

    value = ctx.data.get(input_key)
    if wrap_key:
        payload = {str(wrap_key): value}
    else:
        payload = {"data": value}

    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    ctx.logger.info("webhook: %s %s", method, _redacted_url_for_log(url))
    try:
        resp = requests.request(method, url, json=payload, headers=headers, timeout=30)
    except Exception as exc:
        raise RuntimeError(f"output.webhook: request failed: {exc}") from exc

    ctx.data["webhook_status_code"] = resp.status_code
    ctx.logger.info("webhook: response status=%d", resp.status_code)

    if raise_on_error and not resp.ok:
        raise RuntimeError(f"output.webhook: server returned {resp.status_code}: {resp.text[:200]}")
    return ctx


MODULE = ModuleSpec(
    name="webhook",
    version="0.1.0",
    category="output",
    description="Send context data as a JSON POST (or other HTTP method) to a webhook URL.",
    handler=handle,
    dependencies=(Dependency(name="requests", kind="binary", hint="pip install requests"),),
    config_schema=(
        ConfigField(name="url", description="Webhook URL", required=True),
        ConfigField(name="method", description="HTTP method", default="POST"),
        ConfigField(name="input_key", description="Context key to read data from", default="output_text"),
        ConfigField(name="headers", description="Additional HTTP headers dict", default={}),
        ConfigField(name="wrap_key", description="If set, wrap data under this JSON key", default=None),
        ConfigField(name="raise_on_error", description="Raise on non-2xx response", type="bool", default=True),
    ),
    reads=(ContextKey("output_text", "Data to send (configurable via input_key)"),),
    writes=(ContextKey("webhook_status_code", "HTTP response status code"),),
    safety="trusted_only",
    network=True,
)
