"""RssPollTrigger — polls an RSS/Atom feed for new items."""

from __future__ import annotations

import logging
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import defusedxml.ElementTree as SafeET

from ..queueing import enqueue_jobs
from .spec import Trigger
from ._state import _state_db, _is_seen, _mark_seen

logger = logging.getLogger(__name__)


class RssPollTrigger:
    def __init__(
        self,
        trigger: Trigger,
        cache_dir: Path,
        state_db_path: Path,
        stop_event: threading.Event,
        config=None,
    ) -> None:
        self.trigger = trigger
        self.cache_dir = cache_dir
        self.state_db_path = state_db_path
        self.stop_event = stop_event
        self._config = config

    def _fetch_items(self, url: str) -> list[dict]:
        from ..modules._helpers import fetch_with_redirect_guard

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning(
                "trigger[%s]: RSS URL scheme '%s' is not allowed; skipping",
                self.trigger.name,
                parsed.scheme or "(empty)",
            )
            return []
        _mode = str(getattr(getattr(self._config, "security", None), "mode", "trusted")).lower()
        block_private = _mode == "untrusted"
        try:
            resp = fetch_with_redirect_guard(
                url,
                context=f"trigger[{self.trigger.name}]",
                block_private=block_private,
                user_agent="solux-trigger/0.1.0",
            )
            xml_bytes = resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("trigger[%s]: RSS fetch failed: %s", self.trigger.name, exc)
            return []
        try:
            root = SafeET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            logger.warning("trigger[%s]: RSS parse failed: %s", self.trigger.name, exc)
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []
        # RSS
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                guid = item.findtext("guid") or item.findtext("link") or ""
                link = item.findtext("link") or ""
                items.append({"guid": guid.strip(), "link": link.strip()})
        else:
            # Atom
            for entry in root.findall("atom:entry", ns) or root.findall("entry"):
                guid = entry.findtext("atom:id", namespaces=ns) or entry.findtext("id") or ""
                link_el = entry.find("atom:link", ns) or entry.find("link")
                link = ""
                if link_el is not None:
                    link = link_el.get("href", "") or (link_el.text or "")
                items.append({"guid": guid.strip(), "link": link.strip()})
        return items

    def run(self) -> None:
        cfg = self.trigger.config
        url = str(cfg.get("url", ""))
        interval = float(cfg.get("interval", 300))
        trigger_name = self.trigger.name

        if not url:
            logger.error("trigger[%s]: 'url' is required for rss_poll", trigger_name)
            return
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https"):
            logger.error(
                "trigger[%s]: RSS URL scheme '%s' is not allowed; trigger will not run",
                trigger_name,
                parsed_url.scheme or "(empty)",
            )
            return

        conn = _state_db(self.state_db_path)
        logger.info("trigger[%s]: polling RSS %s every %.1fs", trigger_name, url, interval)
        try:
            while not self.stop_event.is_set():
                items = self._fetch_items(url)
                for item in items:
                    guid = item.get("guid", "") or item.get("link", "")
                    link = item.get("link", "") or guid
                    if not guid or not link:
                        continue
                    if not _is_seen(conn, trigger_name, guid):
                        # Mark seen before enqueueing so a crash between the two
                        # steps never produces duplicate jobs (prefer at-most-once).
                        _mark_seen(conn, trigger_name, guid)
                        logger.info("trigger[%s]: new RSS item: %s", trigger_name, link)
                        try:
                            params = {
                                **dict(self.trigger.params),
                                "_trigger_name": trigger_name,
                                "_trigger_type": self.trigger.type,
                            }
                            enqueue_jobs(
                                self.cache_dir,
                                sources=[link],
                                workflow_name=self.trigger.workflow,
                                params=params,
                            )
                        except Exception as exc:
                            logger.warning("trigger[%s]: enqueue failed: %s", trigger_name, exc)
                self.stop_event.wait(timeout=interval)
        finally:
            conn.close()
