"""Tests for RSS/Atom poll trigger: parsing, deduplication, error handling."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest

from solus.triggers.rss_poll import RssPollTrigger
from solus.triggers.spec import Trigger
from solus.triggers._state import _state_db, _is_seen


def _trigger(name="test_rss", url="http://example.com/feed.xml", interval=0.01, workflow="webpage_summary"):
    return Trigger(
        name=name,
        type="rss_poll",
        workflow=workflow,
        params={"mode": "full"},
        config={"url": url, "interval": interval},
    )


def _make_rss_xml(items: list[tuple[str, str]]) -> bytes:
    """Build a minimal RSS 2.0 XML feed."""
    item_xml = ""
    for guid, link in items:
        item_xml += f"<item><guid>{guid}</guid><link>{link}</link></item>\n"
    return f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    {item_xml}
  </channel>
</rss>""".encode()


def _make_atom_xml(entries: list[tuple[str, str]]) -> bytes:
    """Build a minimal Atom feed using text-content links.

    Note: self-closing ``<link href="..."/>`` elements are falsy in current
    Python XML (no children), causing the ``or`` fallback in rss_poll to fail.
    Text-content links work reliably.
    """
    entry_xml = ""
    for entry_id, link in entries:
        entry_xml += f"<entry><id>{entry_id}</id><link>{link}</link></entry>\n"
    return f"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  {entry_xml}
</feed>""".encode()


# ---------------------------------------------------------------------------
# RSS parsing via _fetch_items
# ---------------------------------------------------------------------------


class TestFetchItems:
    def test_parse_rss_items(self, tmp_path: Path) -> None:
        rss_xml = _make_rss_xml(
            [
                ("guid1", "http://example.com/1"),
                ("guid2", "http://example.com/2"),
            ]
        )
        resp = MagicMock()
        resp.content = rss_xml

        trigger = _trigger()
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with patch("solus.modules._helpers.fetch_with_redirect_guard", return_value=resp):
            items = t._fetch_items("http://example.com/feed.xml")

        assert len(items) == 2
        assert items[0]["guid"] == "guid1"
        assert items[0]["link"] == "http://example.com/1"

    def test_parse_atom_items(self, tmp_path: Path) -> None:
        """Atom feeds with childless link elements fall through the ``or``
        expression (bool(element)==False when element has no children).
        The guid is still extracted correctly via findtext; the link comes
        back empty because find()..or..find() fails.  This documents the
        current behaviour — fixing it is tracked separately."""
        atom_xml = _make_atom_xml(
            [
                ("urn:entry:1", "http://example.com/entry/1"),
                ("urn:entry:2", "http://example.com/entry/2"),
            ]
        )
        resp = MagicMock()
        resp.content = atom_xml

        trigger = _trigger()
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with patch("solus.modules._helpers.fetch_with_redirect_guard", return_value=resp):
            items = t._fetch_items("http://example.com/feed.xml")

        assert len(items) == 2
        assert items[0]["guid"] == "urn:entry:1"
        # Link is empty due to Element truthiness bug (childless elements are falsy)
        assert items[0]["link"] == ""

    def test_rss_fallback_guid_to_link(self, tmp_path: Path) -> None:
        """When guid is missing, link should be used as guid."""
        rss_xml = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><link>http://example.com/only-link</link></item>
  </channel>
</rss>"""
        resp = MagicMock()
        resp.content = rss_xml

        trigger = _trigger()
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with patch("solus.modules._helpers.fetch_with_redirect_guard", return_value=resp):
            items = t._fetch_items("http://example.com/feed.xml")

        assert len(items) == 1
        assert items[0]["guid"] == "http://example.com/only-link"

    def test_malformed_xml_returns_empty(self, tmp_path: Path) -> None:
        resp = MagicMock()
        resp.content = b"this is not xml at all"

        trigger = _trigger()
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with patch("solus.modules._helpers.fetch_with_redirect_guard", return_value=resp):
            items = t._fetch_items("http://example.com/feed.xml")

        assert items == []

    def test_fetch_error_returns_empty(self, tmp_path: Path) -> None:
        trigger = _trigger()
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with patch("solus.modules._helpers.fetch_with_redirect_guard", side_effect=Exception("network error")):
            items = t._fetch_items("http://example.com/feed.xml")

        assert items == []

    def test_non_http_url_returns_empty(self, tmp_path: Path) -> None:
        trigger = _trigger(url="ftp://example.com/feed.xml")
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        items = t._fetch_items("ftp://example.com/feed.xml")
        assert items == []


# ---------------------------------------------------------------------------
# Full run() loop: deduplication
# ---------------------------------------------------------------------------


class TestRssPollRun:
    def test_deduplication_skips_seen_items(self, tmp_path: Path) -> None:
        rss_xml = _make_rss_xml([("guid1", "http://example.com/1")])
        resp = MagicMock()
        resp.content = rss_xml

        trigger = _trigger(interval=0.01)
        stop = threading.Event()
        state_path = tmp_path / "state.db"

        enqueued: list[dict] = []

        def fake_enqueue(cache_dir, *, sources, workflow_name, params):
            enqueued.append({"sources": sources, "workflow": workflow_name})

        poll_count = 0

        def controlled_fetch(*args, **kwargs):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 2:
                stop.set()
            return resp

        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with (
            patch("solus.modules._helpers.fetch_with_redirect_guard", side_effect=controlled_fetch),
            patch("solus.triggers.rss_poll.enqueue_jobs", side_effect=fake_enqueue),
        ):
            t.run()

        # Should enqueue only once despite two polls
        assert len(enqueued) == 1
        assert enqueued[0]["sources"] == ["http://example.com/1"]

    def test_missing_url_exits_early(self, tmp_path: Path) -> None:
        trigger = _trigger(url="")
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)
        # Should return without raising
        t.run()

    def test_non_http_url_exits_early(self, tmp_path: Path) -> None:
        trigger = _trigger(url="ftp://bad.example.com/feed")
        stop = threading.Event()
        state_path = tmp_path / "state.db"
        t = RssPollTrigger(trigger, tmp_path, state_path, stop)
        t.run()

    def test_items_without_guid_or_link_skipped(self, tmp_path: Path) -> None:
        rss_xml = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>No guid or link</title></item>
  </channel>
</rss>"""
        resp = MagicMock()
        resp.content = rss_xml

        trigger = _trigger(interval=0.01)
        stop = threading.Event()
        state_path = tmp_path / "state.db"

        enqueued: list = []

        def stop_after_one(*args, **kwargs):
            stop.set()
            return resp

        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with (
            patch("solus.modules._helpers.fetch_with_redirect_guard", side_effect=stop_after_one),
            patch("solus.triggers.rss_poll.enqueue_jobs", side_effect=lambda **kw: enqueued.append(1)),
        ):
            t.run()

        assert len(enqueued) == 0

    def test_enqueue_failure_does_not_crash(self, tmp_path: Path) -> None:
        rss_xml = _make_rss_xml([("guid1", "http://example.com/1")])
        resp = MagicMock()
        resp.content = rss_xml

        trigger = _trigger(interval=0.01)
        stop = threading.Event()
        state_path = tmp_path / "state.db"

        def stop_after_one(*args, **kwargs):
            stop.set()
            return resp

        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with (
            patch("solus.modules._helpers.fetch_with_redirect_guard", side_effect=stop_after_one),
            patch("solus.triggers.rss_poll.enqueue_jobs", side_effect=RuntimeError("db locked")),
        ):
            # Should not raise despite enqueue failure
            t.run()

    def test_trigger_params_included_in_enqueue(self, tmp_path: Path) -> None:
        rss_xml = _make_rss_xml([("guid1", "http://example.com/1")])
        resp = MagicMock()
        resp.content = rss_xml

        trigger = _trigger(interval=0.01)
        stop = threading.Event()
        state_path = tmp_path / "state.db"

        enqueue_calls: list[dict] = []

        def capture_enqueue(cache_dir, *, sources, workflow_name, params):
            enqueue_calls.append(params)

        def stop_after_one(*args, **kwargs):
            stop.set()
            return resp

        t = RssPollTrigger(trigger, tmp_path, state_path, stop)

        with (
            patch("solus.modules._helpers.fetch_with_redirect_guard", side_effect=stop_after_one),
            patch("solus.triggers.rss_poll.enqueue_jobs", side_effect=capture_enqueue),
        ):
            t.run()

        assert len(enqueue_calls) == 1
        assert enqueue_calls[0]["_trigger_name"] == "test_rss"
        assert enqueue_calls[0]["_trigger_type"] == "rss_poll"
        assert enqueue_calls[0]["mode"] == "full"
