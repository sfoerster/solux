from __future__ import annotations

import smtplib
from email.message import EmailMessage

from solux.modules._helpers import interpolate_env
from solux.modules.spec import ConfigField, ContextKey, ModuleSpec
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    smtp_host = interpolate_env(str(step.config.get("smtp_host", "")))
    smtp_port = int(step.config.get("smtp_port", 587))
    smtp_user = interpolate_env(str(step.config.get("smtp_user", "")))
    smtp_password = interpolate_env(str(step.config.get("smtp_password", "")))
    from_addr = interpolate_env(str(step.config.get("from_addr", smtp_user)))
    to_addr_raw = step.config.get("to_addr", "")
    subject_template = str(step.config.get("subject_template", "Solux: {display_name}"))
    input_key = str(step.config.get("input_key", "output_text"))
    use_tls = bool(step.config.get("use_tls", True))

    if not smtp_host:
        raise RuntimeError("output.email_send: 'smtp_host' is required")

    if isinstance(to_addr_raw, list):
        to_addrs = [interpolate_env(str(a)) for a in to_addr_raw]
    else:
        to_addrs = [interpolate_env(str(to_addr_raw))]

    if not to_addrs or not to_addrs[0]:
        raise RuntimeError("output.email_send: 'to_addr' is required")

    body = str(ctx.data.get(input_key, ""))
    display_name = str(ctx.data.get("display_name") or ctx.source)

    # Sanitize all string values used in headers to prevent header injection.
    # CR and LF are the delimiters between headers; stripping them is sufficient.
    def _sanitize(val: object) -> str:
        return str(val).replace("\r", "").replace("\n", "")

    format_vars = {k: _sanitize(v) for k, v in ctx.data.items()}
    format_vars["display_name"] = _sanitize(display_name)
    format_vars["source"] = _sanitize(ctx.source)
    try:
        subject = subject_template.format_map(format_vars)
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError(f"output.email_send: invalid subject_template: {exc}") from exc

    msg = EmailMessage()
    msg["From"] = _sanitize(from_addr)
    msg["To"] = ", ".join(_sanitize(a) for a in to_addrs)
    msg["Subject"] = _sanitize(subject)
    msg.set_content(body)

    try:
        if use_tls:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"output.email_send: SMTP error: {exc}") from exc

    message_id = str(msg.get("Message-ID", ""))
    ctx.data["email_sent"] = True
    ctx.data["email_message_id"] = message_id
    ctx.logger.info("email_send: sent to %s", ", ".join(to_addrs))
    return ctx


MODULE = ModuleSpec(
    name="email_send",
    version="0.1.0",
    category="output",
    description="Send an email via SMTP (stdlib smtplib, zero new deps).",
    handler=handle,
    aliases=("output.email",),
    dependencies=(),
    config_schema=(
        ConfigField(name="smtp_host", description="SMTP server hostname", required=True),
        ConfigField(name="smtp_port", description="SMTP server port", type="int", default=587),
        ConfigField(name="smtp_user", description="SMTP username"),
        ConfigField(name="smtp_password", description="SMTP password (supports ${env:VAR})"),
        ConfigField(name="from_addr", description="Sender address (default: smtp_user)"),
        ConfigField(name="to_addr", description="Recipient address or list"),
        ConfigField(
            name="subject_template",
            description="Subject template (supports {display_name} etc.)",
            default="Solux: {display_name}",
        ),
        ConfigField(name="input_key", description="Context key for email body", default="output_text"),
        ConfigField(name="use_tls", description="Use STARTTLS", type="bool", default=True),
    ),
    reads=(
        ContextKey("output_text", "Email body (configurable via input_key)"),
        ContextKey("display_name", "Used in subject template"),
    ),
    writes=(
        ContextKey("email_sent", "True if email was sent successfully"),
        ContextKey("email_message_id", "Message-ID header from sent email"),
    ),
    safety="trusted_only",
    network=True,
)
