from __future__ import annotations

import json
from urllib.parse import urlparse

import requests

from solus.modules._helpers import interpolate_env
from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def _redacted_url_for_log(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "[redacted]"
    host = parsed.netloc.split("@")[-1]
    return f"{parsed.scheme}://{host}"


def handle(ctx: Context, step: Step) -> Context:
    webhook_url = interpolate_env(str(step.config.get("webhook_url", "")))
    if not webhook_url:
        raise RuntimeError("output.slack_notify: 'webhook_url' is required")

    input_key = str(step.config.get("input_key", "output_text"))
    message_template = step.config.get("message_template")
    username = step.config.get("username", "Solus")
    icon_emoji = step.config.get("icon_emoji", ":robot_face:")
    raise_on_error = bool(step.config.get("raise_on_error", True))

    body = str(ctx.data.get(input_key, ""))

    if message_template:
        format_vars = dict(ctx.data)
        format_vars["output_text"] = body
        format_vars["source"] = ctx.source
        format_vars["display_name"] = str(ctx.data.get("display_name") or ctx.source)
        try:
            text = str(message_template).format_map(format_vars)
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError(f"output.slack_notify: invalid message_template: {exc}") from exc
    else:
        text = body

    payload: dict = {"text": text}
    if username:
        payload["username"] = str(username)
    if icon_emoji:
        payload["icon_emoji"] = str(icon_emoji)

    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"output.slack_notify: request failed: {exc}") from exc

    ctx.data["slack_status_code"] = resp.status_code
    ctx.logger.info("slack_notify: POST %s -> %d", _redacted_url_for_log(webhook_url), resp.status_code)
    if raise_on_error and not resp.ok:
        raise RuntimeError(f"output.slack_notify: server returned {resp.status_code}: {resp.text[:200]}")
    return ctx


MODULE = ModuleSpec(
    name="slack_notify",
    version="0.1.0",
    category="output",
    description="Send a message to a Slack channel via incoming webhook.",
    handler=handle,
    aliases=("output.slack",),
    dependencies=(),
    config_schema=(
        ConfigField(name="webhook_url", description="Slack incoming webhook URL (supports ${env:VAR})", required=True),
        ConfigField(name="input_key", description="Context key for message body", default="output_text"),
        ConfigField(name="message_template", description="Optional message template with {placeholders}"),
        ConfigField(name="username", description="Bot display name", default="Solus"),
        ConfigField(name="icon_emoji", description="Bot emoji icon", default=":robot_face:"),
        ConfigField(name="raise_on_error", description="Raise on non-2xx response", type="bool", default=True),
    ),
    reads=(ContextKey("output_text", "Message text (configurable via input_key)"),),
    writes=(ContextKey("slack_status_code", "HTTP status code from Slack webhook"),),
    safety="trusted_only",
    network=True,
)
