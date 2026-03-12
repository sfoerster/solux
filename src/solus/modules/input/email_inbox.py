from __future__ import annotations

import email
import imaplib

from solus.modules._helpers import interpolate_env
from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def _decode_header(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return str(value)
    return str(value)


def _get_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def handle(ctx: Context, step: Step) -> Context:
    host = str(step.config.get("host", ""))
    port = int(step.config.get("port", 993))
    username = interpolate_env(str(step.config.get("username", "")))
    password = interpolate_env(str(step.config.get("password", "")))
    folder = str(step.config.get("folder", "INBOX"))
    limit = int(step.config.get("limit", 10))
    unseen_only = bool(step.config.get("unseen_only", True))
    output_key = str(step.config.get("output_key", "messages"))

    if not host:
        raise RuntimeError("input.email_inbox: 'host' is required")
    if not username or not password:
        raise RuntimeError("input.email_inbox: 'username' and 'password' are required")

    try:
        imap = imaplib.IMAP4_SSL(host, port, timeout=30)
        imap.login(username, password)
        imap.select(folder)

        search_criteria = "UNSEEN" if unseen_only else "ALL"
        status, data = imap.search(None, search_criteria)
        if status != "OK":
            raise RuntimeError(f"input.email_inbox: IMAP search failed: {status}")

        uid_list = data[0].split() if data[0] else []
        uid_list = uid_list[-limit:] if limit > 0 else uid_list

        messages = []
        for uid in uid_list:
            status2, msg_data = imap.fetch(uid, "(RFC822)")
            if status2 != "OK" or not msg_data:
                continue
            raw = msg_data[0]
            if not isinstance(raw, tuple):
                continue
            msg = email.message_from_bytes(raw[1])
            body = _get_body(msg)
            snippet = body[:200].replace("\n", " ").strip()
            messages.append(
                {
                    "uid": uid.decode("ascii"),
                    "subject": _decode_header(msg.get("Subject")),
                    "from": _decode_header(msg.get("From")),
                    "date": _decode_header(msg.get("Date")),
                    "body": body,
                    "snippet": snippet,
                }
            )

        imap.logout()
    except imaplib.IMAP4.error as exc:
        raise RuntimeError(f"input.email_inbox: IMAP error: {exc}") from exc

    ctx.data[output_key] = messages
    ctx.data["display_name"] = f"inbox:{folder}"
    ctx.logger.info("email_inbox: fetched %d messages from %s/%s", len(messages), host, folder)
    return ctx


MODULE = ModuleSpec(
    name="email_inbox",
    version="0.1.0",
    category="input",
    description="Fetch messages from an IMAP email inbox.",
    handler=handle,
    aliases=("input.email",),
    dependencies=(),
    config_schema=(
        ConfigField(name="host", description="IMAP server hostname", required=True),
        ConfigField(name="port", description="IMAP port (default 993 SSL)", type="int", default=993),
        ConfigField(name="username", description="IMAP username (supports ${env:VAR})", required=True),
        ConfigField(name="password", description="IMAP password (supports ${env:VAR})", required=True),
        ConfigField(name="folder", description="Mailbox folder", default="INBOX"),
        ConfigField(name="limit", description="Max messages to fetch", type="int", default=10),
        ConfigField(name="unseen_only", description="Fetch only unread messages", type="bool", default=True),
        ConfigField(name="output_key", description="Context key for messages list", default="messages"),
    ),
    reads=(),
    writes=(
        ContextKey("messages", "List of message dicts (uid, subject, from, date, body, snippet)"),
        ContextKey("display_name", "inbox:<folder>"),
    ),
    safety="trusted_only",
    network=True,
)
