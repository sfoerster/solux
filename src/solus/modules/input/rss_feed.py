from __future__ import annotations

import xml.etree.ElementTree as ET

import defusedxml.ElementTree as SafeET
import requests

from solus.modules._helpers import fetch_with_redirect_guard
from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    url = str(step.config.get("url", ""))
    if not url:
        raise RuntimeError("input.rss_feed: 'url' config is required")
    _mode = str(getattr(getattr(ctx.config, "security", None), "mode", "trusted")).lower()
    block_private = _mode == "untrusted"
    limit = int(step.config.get("limit", 10))
    if limit < 1:
        limit = 10
    output_key = str(step.config.get("output_key", "feed_items"))

    ctx.logger.info("rss_feed: fetching %s", url)
    try:
        resp = fetch_with_redirect_guard(
            url,
            context="input.rss_feed",
            block_private=block_private,
        )
        xml_bytes = resp.content
    except requests.RequestException as exc:
        raise RuntimeError(f"input.rss_feed: failed to fetch {url}: {exc}") from exc
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"input.rss_feed: failed to fetch {url}: {exc}") from exc

    try:
        root = SafeET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise RuntimeError(f"input.rss_feed: failed to parse XML: {exc}") from exc

    # Support both RSS (<channel>) and Atom (<feed>) formats
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    feed_title = ""

    # RSS format
    channel = root.find("channel")
    if channel is not None:
        title_el = channel.find("title")
        if title_el is not None and title_el.text:
            feed_title = title_el.text.strip()
        raw_items = channel.findall("item")
        items = []
        for item in raw_items[:limit]:
            entry = {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "summary": (item.findtext("description") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
            }
            items.append(entry)
    else:
        # Atom format
        title_el = root.find("atom:title", ns)
        if title_el is None:
            title_el = root.find("title")
        if title_el is not None and title_el.text:
            feed_title = title_el.text.strip()
        raw_entries = root.findall("atom:entry", ns) or root.findall("entry")
        items = []
        for entry_el in raw_entries[:limit]:
            link_el = entry_el.find("atom:link", ns)
            if link_el is None:
                link_el = entry_el.find("link")
            link = ""
            if link_el is not None:
                link = link_el.get("href", "") or (link_el.text or "")
            entry = {
                "title": (entry_el.findtext("atom:title", namespaces=ns) or entry_el.findtext("title") or "").strip(),
                "link": link.strip(),
                "summary": (
                    entry_el.findtext("atom:summary", namespaces=ns) or entry_el.findtext("summary") or ""
                ).strip(),
                "published": (
                    entry_el.findtext("atom:published", namespaces=ns) or entry_el.findtext("published") or ""
                ).strip(),
            }
            items.append(entry)

    ctx.data[output_key] = items
    if feed_title:
        ctx.data["display_name"] = feed_title
    ctx.logger.info("rss_feed: fetched %d items from %s", len(items), feed_title or url)
    return ctx


MODULE = ModuleSpec(
    name="rss_feed",
    version="0.1.0",
    category="input",
    description="Fetch and parse an RSS or Atom feed; returns a list of item dicts.",
    handler=handle,
    config_schema=(
        ConfigField(name="url", description="RSS/Atom feed URL", required=True),
        ConfigField(name="limit", description="Max number of items to return", type="int", default=10),
        ConfigField(name="output_key", description="Context key to write items list to", default="feed_items"),
    ),
    reads=(),
    writes=(
        ContextKey("feed_items", "List of feed item dicts (title, link, summary, published)"),
        ContextKey("display_name", "Feed title"),
    ),
    network=True,
)
