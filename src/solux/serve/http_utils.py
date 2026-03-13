from __future__ import annotations

import re
from email.message import Message

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MiB
MAX_WEBHOOK_BYTES = 1 * 1024 * 1024  # 1 MiB — machine-to-machine JSON payloads
MAX_API_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB — form posts from the web UI

_WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def is_safe_workflow_name(name: str) -> bool:
    return bool(_WORKFLOW_NAME_RE.fullmatch(name))


def parse_multipart_form(body: bytes, boundary: bytes) -> list[dict]:
    """Parse multipart/form-data using the stdlib email module (RFC 2046)."""
    import email as _email_stdlib

    boundary_str = boundary.decode("latin-1")
    # Construct a minimal MIME envelope so the email parser can process it.
    header = f"Content-Type: multipart/form-data; boundary={boundary_str}\r\n\r\n".encode("latin-1")
    msg = _email_stdlib.message_from_bytes(header + body)
    parts: list[dict] = []
    if not msg.is_multipart():
        return parts
    payload = msg.get_payload()
    if not isinstance(payload, list):
        return parts
    for part in payload:
        if not isinstance(part, Message):
            continue
        disposition = str(part.get("Content-Disposition", ""))
        name_match = re.search(r'name="([^"]*)"', disposition)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        part_payload = part.get_payload(decode=True)
        payload_bytes = part_payload if isinstance(part_payload, bytes) else b""
        parts.append(
            {
                "name": name_match.group(1) if name_match else "",
                "filename": filename_match.group(1) if filename_match else None,
                "data": payload_bytes,
            }
        )
    return parts
