"""Tests for the 8 new modules added in Phase 3."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from solus.workflows.models import Context, Step


def _ctx(data: dict | None = None, source: str = "test", params: dict | None = None) -> Context:
    config = MagicMock()
    config.ollama.base_url = "http://localhost:11434"
    config.ollama.model = "llama3.1:8b"
    return Context(
        source=source,
        source_id="test001",
        data=data or {},
        config=config,
        logger=logging.getLogger("test"),
        params=params or {},
    )


def _step(step_type: str, config: dict | None = None) -> Step:
    return Step(name="step", type=step_type, config=config or {})


# ---------------------------------------------------------------------------
# input.rss_feed
# ---------------------------------------------------------------------------

RSS_XML = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>My Podcast</title>
    <item>
      <title>Episode 1</title>
      <link>http://example.com/ep1.mp3</link>
      <description>First episode</description>
      <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Episode 2</title>
      <link>http://example.com/ep2.mp3</link>
      <description>Second episode</description>
      <pubDate>Tue, 02 Jan 2024 00:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

ATOM_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Item One</title>
    <link href="http://example.com/one"/>
    <summary>Summary one</summary>
    <published>2024-01-01T00:00:00Z</published>
  </entry>
</feed>"""


@patch("solus.modules.input.rss_feed.requests.get")
def test_rss_feed_rss_format(mock_get) -> None:
    from solus.modules.input.rss_feed import handle

    mock_resp = MagicMock()
    mock_resp.content = RSS_XML
    mock_resp.is_redirect = False
    mock_resp.is_permanent_redirect = False
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    ctx = _ctx()
    step = _step("input.rss_feed", {"url": "http://feeds.example.com/rss"})
    result = handle(ctx, step)

    assert result.data["display_name"] == "My Podcast"
    items = result.data["feed_items"]
    assert len(items) == 2
    assert items[0]["title"] == "Episode 1"
    assert items[0]["link"] == "http://example.com/ep1.mp3"
    assert items[0]["summary"] == "First episode"


@patch("solus.modules.input.rss_feed.requests.get")
def test_rss_feed_atom_format(mock_get) -> None:
    from solus.modules.input.rss_feed import handle

    mock_resp = MagicMock()
    mock_resp.content = ATOM_XML
    mock_resp.is_redirect = False
    mock_resp.is_permanent_redirect = False
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    ctx = _ctx()
    step = _step("input.rss_feed", {"url": "http://feeds.example.com/atom"})
    result = handle(ctx, step)

    assert result.data["display_name"] == "Atom Feed"
    items = result.data["feed_items"]
    assert len(items) == 1
    assert items[0]["title"] == "Item One"
    assert items[0]["link"] == "http://example.com/one"


@patch("solus.modules.input.rss_feed.requests.get")
def test_rss_feed_limit(mock_get) -> None:
    from solus.modules.input.rss_feed import handle

    mock_resp = MagicMock()
    mock_resp.content = RSS_XML
    mock_resp.is_redirect = False
    mock_resp.is_permanent_redirect = False
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    ctx = _ctx()
    step = _step("input.rss_feed", {"url": "http://feeds.example.com/rss", "limit": 1})
    result = handle(ctx, step)

    assert len(result.data["feed_items"]) == 1


def test_rss_feed_missing_url_raises() -> None:
    from solus.modules.input.rss_feed import handle

    ctx = _ctx()
    step = _step("input.rss_feed", {})
    with pytest.raises(RuntimeError, match="'url' config is required"):
        handle(ctx, step)


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/feeds.xml",
        "ftp://ftp.example.com/rss.xml",
    ],
)
def test_rss_feed_rejects_non_http_urls(bad_url: str) -> None:
    from solus.modules.input.rss_feed import handle

    ctx = _ctx()
    step = _step("input.rss_feed", {"url": bad_url})
    with pytest.raises(RuntimeError, match="URL scheme"):
        handle(ctx, step)


@patch("solus.modules.input.rss_feed.requests.get")
def test_rss_feed_custom_output_key(mock_get) -> None:
    from solus.modules.input.rss_feed import handle

    mock_resp = MagicMock()
    mock_resp.content = RSS_XML
    mock_resp.is_redirect = False
    mock_resp.is_permanent_redirect = False
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    ctx = _ctx()
    step = _step("input.rss_feed", {"url": "http://feeds.example.com/rss", "output_key": "items"})
    result = handle(ctx, step)

    assert "items" in result.data
    assert "feed_items" not in result.data


# ---------------------------------------------------------------------------
# input.folder_watch
# ---------------------------------------------------------------------------


def test_folder_watch_finds_files(tmp_path: Path) -> None:
    from solus.modules.input.folder_watch import handle

    (tmp_path / "ep1.mp3").write_text("audio")
    (tmp_path / "ep2.mp3").write_text("audio")
    (tmp_path / "notes.txt").write_text("text")

    ctx = _ctx()
    step = _step("input.folder_watch", {"path": str(tmp_path), "pattern": "*.mp3"})
    result = handle(ctx, step)

    files = result.data["found_files"]
    assert len(files) == 2
    assert all(f.endswith(".mp3") for f in files)


def test_folder_watch_missing_path_raises() -> None:
    from solus.modules.input.folder_watch import handle

    ctx = _ctx()
    step = _step("input.folder_watch", {})
    with pytest.raises(RuntimeError, match="'path' config is required"):
        handle(ctx, step)


def test_folder_watch_nonexistent_dir_returns_empty(tmp_path: Path) -> None:
    from solus.modules.input.folder_watch import handle

    ctx = _ctx()
    step = _step("input.folder_watch", {"path": str(tmp_path / "no_such_dir")})
    result = handle(ctx, step)
    assert result.data["found_files"] == []


def test_folder_watch_custom_output_key(tmp_path: Path) -> None:
    from solus.modules.input.folder_watch import handle

    (tmp_path / "file.txt").write_text("x")
    ctx = _ctx()
    step = _step("input.folder_watch", {"path": str(tmp_path), "output_key": "my_files"})
    result = handle(ctx, step)
    assert "my_files" in result.data


# ---------------------------------------------------------------------------
# input.parse_pdf (soft-import)
# ---------------------------------------------------------------------------


def test_parse_pdf_missing_pypdf_raises(tmp_path: Path) -> None:
    """If pypdf is not installed, RuntimeError with install hint is raised."""
    import sys
    from solus.modules.input import parse_pdf

    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    ctx = _ctx(source=str(pdf_path))
    step = _step("input.parse_pdf", {})

    # Simulate pypdf not being installed by removing it from sys.modules
    # and making the import fail via builtins.__import__
    original = sys.modules.pop("pypdf", None)
    try:
        with patch(
            "builtins.__import__",
            side_effect=lambda name, *a, **kw: (
                (_ for _ in ()).throw(ImportError("no module named pypdf"))
                if name == "pypdf"
                else __import__(name, *a, **kw)
            ),
        ):
            with pytest.raises(RuntimeError, match="pypdf"):
                parse_pdf.handle(ctx, step)
    finally:
        if original is not None:
            sys.modules["pypdf"] = original


def test_parse_pdf_with_mock_pypdf(tmp_path: Path) -> None:
    from solus.modules.input import parse_pdf

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    ctx = _ctx(source=str(pdf_path))
    step = _step("input.parse_pdf", {})

    mock_reader = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Page text here"
    mock_reader.pages = [mock_page]

    mock_pypdf = MagicMock()
    mock_pypdf.PdfReader.return_value = mock_reader

    import sys

    sys.modules["pypdf"] = mock_pypdf
    try:
        import importlib

        importlib.reload(parse_pdf)
        result = parse_pdf.handle(ctx, step)
    finally:
        del sys.modules["pypdf"]
        importlib.reload(parse_pdf)

    assert result.data["pdf_text"] == "Page text here"
    assert result.data["display_name"] == "test.pdf"


# ---------------------------------------------------------------------------
# output.webhook
# ---------------------------------------------------------------------------


@patch("solus.modules.output.webhook.requests.request")
def test_webhook_post_default(mock_request) -> None:
    from solus.modules.output.webhook import handle

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_request.return_value = mock_resp

    ctx = _ctx(data={"output_text": "hello world"})
    step = _step("output.webhook", {"url": "http://example.com/hook"})
    result = handle(ctx, step)

    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    assert call_kwargs[0][0] == "POST"
    assert call_kwargs[0][1] == "http://example.com/hook"
    assert call_kwargs[1]["json"] == {"data": "hello world"}
    assert result.data["webhook_status_code"] == 200


@patch("solus.modules.output.webhook.requests.request")
def test_webhook_logs_redacted_url(mock_request) -> None:
    from solus.modules.output.webhook import handle

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_request.return_value = mock_resp

    ctx = _ctx(data={"output_text": "hello world"})
    ctx.logger = MagicMock()
    step = _step("output.webhook", {"url": "https://user:secret@example.com/path/with/token?x=1"})
    handle(ctx, step)

    ctx.logger.info.assert_any_call("webhook: %s %s", "POST", "https://example.com")


@patch("solus.modules.output.webhook.requests.request")
def test_webhook_wrap_key(mock_request) -> None:
    from solus.modules.output.webhook import handle

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.ok = True
    mock_request.return_value = mock_resp

    ctx = _ctx(data={"output_text": "content"})
    step = _step("output.webhook", {"url": "http://example.com/hook", "wrap_key": "payload"})
    result = handle(ctx, step)

    call_kwargs = mock_request.call_args
    assert call_kwargs[1]["json"] == {"payload": "content"}
    assert result.data["webhook_status_code"] == 201


@patch("solus.modules.output.webhook.requests.request")
def test_webhook_raises_on_4xx(mock_request) -> None:
    from solus.modules.output.webhook import handle

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.ok = False
    mock_resp.text = "Not Found"
    mock_request.return_value = mock_resp

    ctx = _ctx(data={"output_text": "data"})
    step = _step("output.webhook", {"url": "http://example.com/hook"})
    with pytest.raises(RuntimeError, match="404"):
        handle(ctx, step)


@patch("solus.modules.output.webhook.requests.request")
def test_webhook_no_raise_on_error(mock_request) -> None:
    from solus.modules.output.webhook import handle

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.ok = False
    mock_resp.text = "Server Error"
    mock_request.return_value = mock_resp

    ctx = _ctx(data={"output_text": "data"})
    step = _step("output.webhook", {"url": "http://example.com/hook", "raise_on_error": False})
    result = handle(ctx, step)
    assert result.data["webhook_status_code"] == 500


def test_webhook_missing_url_raises() -> None:
    from solus.modules.output.webhook import handle

    ctx = _ctx(data={"output_text": "data"})
    step = _step("output.webhook", {})
    with pytest.raises(RuntimeError, match="'url' config is required"):
        handle(ctx, step)


# ---------------------------------------------------------------------------
# output.local_db
# ---------------------------------------------------------------------------


def test_local_db_inserts_record(tmp_path: Path) -> None:
    from solus.modules.output.local_db import handle

    db_path = tmp_path / "test.db"
    ctx = _ctx(data={"output_text": "hello"})
    step = _step("output.local_db", {"db_path": str(db_path)})
    result = handle(ctx, step)

    assert "db_record_id" in result.data
    assert result.data["db_record_id"] == 1


def test_local_db_inserts_multiple(tmp_path: Path) -> None:
    from solus.modules.output.local_db import handle

    db_path = tmp_path / "test.db"
    for i in range(3):
        ctx = _ctx(data={"output_text": f"record {i}"})
        step = _step("output.local_db", {"db_path": str(db_path)})
        result = handle(ctx, step)
        assert result.data["db_record_id"] == i + 1


def test_local_db_custom_input_key(tmp_path: Path) -> None:
    from solus.modules.output.local_db import handle
    import sqlite3

    db_path = tmp_path / "test.db"
    ctx = _ctx(data={"summary": "my summary"})
    step = _step("output.local_db", {"db_path": str(db_path), "input_key": "summary"})
    handle(ctx, step)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT content FROM records WHERE id=1").fetchone()
    conn.close()
    assert row[0] == "my summary"


def test_local_db_invalid_table_name_raises(tmp_path: Path) -> None:
    from solus.modules.output.local_db import handle

    db_path = tmp_path / "test.db"
    ctx = _ctx(data={"output_text": "hello"})
    step = _step("output.local_db", {"db_path": str(db_path), "table": "records; DROP TABLE records;--"})
    with pytest.raises(RuntimeError, match="invalid table name"):
        handle(ctx, step)


# ---------------------------------------------------------------------------
# ai.llm_classify
# ---------------------------------------------------------------------------


@patch("solus.modules.ai.llm_classify.call_ollama_chat")
def test_llm_classify_exact_match(mock_chat) -> None:
    from solus.modules.ai.llm_classify import handle

    mock_chat.return_value = "sports"
    ctx = _ctx(data={"input_text": "The team won the championship."})
    step = _step("ai.llm_classify", {"categories": ["sports", "tech", "politics"]})
    result = handle(ctx, step)
    assert result.data["classification"] == "sports"


@patch("solus.modules.ai.llm_classify.call_ollama_chat")
def test_llm_classify_case_insensitive(mock_chat) -> None:
    from solus.modules.ai.llm_classify import handle

    mock_chat.return_value = "TECH"
    ctx = _ctx(data={"input_text": "New AI model released."})
    step = _step("ai.llm_classify", {"categories": ["sports", "tech", "politics"]})
    result = handle(ctx, step)
    assert result.data["classification"] == "tech"


@patch("solus.modules.ai.llm_classify.call_ollama_chat")
def test_llm_classify_fallback_substring(mock_chat) -> None:
    from solus.modules.ai.llm_classify import handle

    mock_chat.return_value = "I think this is about politics and governance."
    ctx = _ctx(data={"input_text": "Election results announced."})
    step = _step("ai.llm_classify", {"categories": ["sports", "tech", "politics"]})
    result = handle(ctx, step)
    assert result.data["classification"] == "politics"


@patch("solus.modules.ai.llm_classify.call_ollama_chat")
def test_llm_classify_custom_output_key(mock_chat) -> None:
    from solus.modules.ai.llm_classify import handle

    mock_chat.return_value = "sports"
    ctx = _ctx(data={"input_text": "Football match."})
    step = _step("ai.llm_classify", {"categories": ["sports", "tech"], "output_key": "category"})
    result = handle(ctx, step)
    assert "category" in result.data
    assert "classification" not in result.data


def test_llm_classify_missing_categories_raises() -> None:
    from solus.modules.ai.llm_classify import handle

    ctx = _ctx(data={"input_text": "some text"})
    step = _step("ai.llm_classify", {})
    with pytest.raises(RuntimeError, match="'categories' config is required"):
        handle(ctx, step)


def test_llm_classify_missing_input_key_raises() -> None:
    from solus.modules.ai.llm_classify import handle

    ctx = _ctx(data={})
    step = _step("ai.llm_classify", {"categories": ["a", "b"]})
    with pytest.raises(RuntimeError, match="missing 'input_text'"):
        handle(ctx, step)


# ---------------------------------------------------------------------------
# ai.llm_extract
# ---------------------------------------------------------------------------


@patch("solus.modules.ai.llm_extract.call_ollama_chat")
def test_llm_extract_json_response(mock_chat) -> None:
    from solus.modules.ai.llm_extract import handle

    mock_chat.return_value = '{"name": "Alice", "age": "30"}'
    ctx = _ctx(data={"input_text": "Alice is 30 years old."})
    step = _step("ai.llm_extract", {"fields": ["name", "age"]})
    result = handle(ctx, step)

    assert result.data["extracted"] == {"name": "Alice", "age": "30"}


@patch("solus.modules.ai.llm_extract.call_ollama_chat")
def test_llm_extract_strips_code_fences(mock_chat) -> None:
    from solus.modules.ai.llm_extract import handle

    mock_chat.return_value = '```json\n{"title": "My Book"}\n```'
    ctx = _ctx(data={"input_text": "My Book, published 2024."})
    step = _step("ai.llm_extract", {"fields": ["title"]})
    result = handle(ctx, step)
    assert result.data["extracted"]["title"] == "My Book"


@patch("solus.modules.ai.llm_extract.call_ollama_chat")
def test_llm_extract_invalid_json_raises(mock_chat) -> None:
    from solus.modules.ai.llm_extract import handle

    mock_chat.return_value = "not json at all"
    ctx = _ctx(data={"input_text": "some text"})
    step = _step("ai.llm_extract", {"fields": ["name"]})
    with pytest.raises(RuntimeError, match="valid JSON"):
        handle(ctx, step)


@patch("solus.modules.ai.llm_extract.call_ollama_chat")
def test_llm_extract_custom_output_key(mock_chat) -> None:
    from solus.modules.ai.llm_extract import handle

    mock_chat.return_value = '{"x": 1}'
    ctx = _ctx(data={"input_text": "x is 1"})
    step = _step("ai.llm_extract", {"fields": ["x"], "output_key": "my_data"})
    result = handle(ctx, step)
    assert "my_data" in result.data
    assert "extracted" not in result.data


def test_llm_extract_missing_fields_raises() -> None:
    from solus.modules.ai.llm_extract import handle

    ctx = _ctx(data={"input_text": "some text"})
    step = _step("ai.llm_extract", {})
    with pytest.raises(RuntimeError, match="'fields' config is required"):
        handle(ctx, step)


# ---------------------------------------------------------------------------
# ai.embeddings
# ---------------------------------------------------------------------------


@patch("solus.modules.ai.embeddings.requests.post")
def test_embeddings_returns_vector(mock_post) -> None:
    from solus.modules.ai.embeddings import handle

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    ctx = _ctx(data={"input_text": "hello world"})
    step = _step("ai.embeddings", {})
    result = handle(ctx, step)

    assert result.data["embedding"] == [0.1, 0.2, 0.3]
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "/api/embeddings" in call_args[0][0]
    assert call_args[1]["json"]["prompt"] == "hello world"


@patch("solus.modules.ai.embeddings.requests.post")
def test_embeddings_model_override(mock_post) -> None:
    from solus.modules.ai.embeddings import handle

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embedding": [0.5]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    ctx = _ctx(data={"input_text": "test"})
    step = _step("ai.embeddings", {"model": "nomic-embed-text"})
    handle(ctx, step)

    call_args = mock_post.call_args
    assert call_args[1]["json"]["model"] == "nomic-embed-text"


@patch("solus.modules.ai.embeddings.requests.post")
def test_embeddings_custom_output_key(mock_post) -> None:
    from solus.modules.ai.embeddings import handle

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embedding": [1.0, 2.0]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    ctx = _ctx(data={"input_text": "text"})
    step = _step("ai.embeddings", {"output_key": "vec"})
    result = handle(ctx, step)
    assert "vec" in result.data
    assert "embedding" not in result.data


def test_embeddings_missing_input_raises() -> None:
    from solus.modules.ai.embeddings import handle

    ctx = _ctx(data={})
    step = _step("ai.embeddings", {})
    with pytest.raises(RuntimeError, match="missing 'input_text'"):
        handle(ctx, step)


@patch("solus.modules.ai.embeddings.requests.post")
def test_embeddings_bad_response_raises(mock_post) -> None:
    from solus.modules.ai.embeddings import handle

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error": "model not found"}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    ctx = _ctx(data={"input_text": "text"})
    step = _step("ai.embeddings", {})
    with pytest.raises(RuntimeError, match="unexpected response"):
        handle(ctx, step)
