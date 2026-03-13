from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from solux import paths
from solux.html_text import html_to_text
from solux.modules._helpers import fetch_with_redirect_guard
from solux.modules.spec import ContextKey, ModuleSpec
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    del step
    url = ctx.source
    _mode = str(getattr(getattr(ctx.config, "security", None), "mode", "trusted")).lower()
    resp = fetch_with_redirect_guard(
        url,
        context="input.webpage_fetch",
        block_private=(_mode == "untrusted"),
    )
    html = resp.text

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    display_name = title_match.group(1).strip() if title_match else url

    text = html_to_text(html)

    ctx.data["webpage_text"] = text
    ctx.data["display_name"] = display_name

    # Write metadata
    now = datetime.now(timezone.utc).isoformat()
    meta_path = paths.metadata_path(ctx.config.paths.cache_dir, ctx.source_id)
    existing: dict[str, str] = {}
    if meta_path.exists():
        try:
            existing_raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(existing_raw, dict):
                existing = {k: str(v) for k, v in existing_raw.items() if isinstance(k, str)}
        except (OSError, json.JSONDecodeError):
            existing = {}

    workflow_name = str(ctx.data.get("workflow_name") or "") or None
    payload: dict[str, str] = {
        "source_id": ctx.source_id,
        "source": url,
        "display_name": display_name,
        "updated_at": now,
        "created_at": existing.get("created_at", now),
    }
    if workflow_name:
        payload["workflow_name"] = workflow_name
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return ctx


MODULE = ModuleSpec(
    name="webpage_fetch",
    version="0.3.0",
    category="input",
    description="Fetch a webpage and extract its text content.",
    handler=handle,
    aliases=(),
    dependencies=(),
    config_schema=(),
    reads=(ContextKey("source", "URL of the webpage to fetch"),),
    writes=(
        ContextKey("webpage_text", "Extracted text content of the webpage"),
        ContextKey("display_name", "Page title or URL used as display name"),
    ),
    network=True,
)
