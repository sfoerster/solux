from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from solus.modules.input.webpage_fetch import handle
from solus.workflows.models import Context, Step

SAMPLE_HTML = """\
<html>
<head><title>Test Page Title</title></head>
<body>
<h1>Hello World</h1>
<p>This is a test paragraph.</p>
</body>
</html>
"""


def _make_context(tmp_path: Path, source: str = "https://example.com") -> Context:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    config = MagicMock()
    config.paths.cache_dir = cache_dir

    return Context(
        source=source,
        source_id="abc123",
        data={},
        config=config,
        logger=logging.getLogger("test"),
    )


def _make_step() -> Step:
    return Step(name="fetch_webpage", type="input.webpage_fetch", config={})


@patch("solus.modules.input.webpage_fetch.fetch_with_redirect_guard")
def test_handle_sets_webpage_text_and_display_name(mock_fetch, tmp_path: Path) -> None:
    resp = MagicMock()
    resp.text = SAMPLE_HTML
    mock_fetch.return_value = resp

    ctx = _make_context(tmp_path)
    step = _make_step()

    result = handle(ctx, step)

    assert "webpage_text" in result.data
    assert "Hello World" in result.data["webpage_text"]
    assert "test paragraph" in result.data["webpage_text"]
    assert result.data["display_name"] == "Test Page Title"


@patch("solus.modules.input.webpage_fetch.fetch_with_redirect_guard")
def test_handle_uses_url_when_no_title(mock_fetch, tmp_path: Path) -> None:
    resp = MagicMock()
    resp.text = "<html><body><p>No title here</p></body></html>"
    mock_fetch.return_value = resp

    ctx = _make_context(tmp_path, source="https://example.com/page")
    step = _make_step()

    result = handle(ctx, step)

    assert result.data["display_name"] == "https://example.com/page"
    assert "No title here" in result.data["webpage_text"]


@patch("solus.modules.input.webpage_fetch.fetch_with_redirect_guard")
def test_handle_writes_metadata(mock_fetch, tmp_path: Path) -> None:
    resp = MagicMock()
    resp.text = SAMPLE_HTML
    mock_fetch.return_value = resp

    ctx = _make_context(tmp_path)
    step = _make_step()

    handle(ctx, step)

    meta_path = tmp_path / "cache" / "sources" / "abc123" / "metadata.json"
    assert meta_path.exists()


@patch("solus.modules.input.webpage_fetch.fetch_with_redirect_guard")
def test_handle_raises_on_http_error(mock_fetch, tmp_path: Path) -> None:
    import requests

    mock_fetch.side_effect = requests.HTTPError("404 Not Found")

    ctx = _make_context(tmp_path)
    step = _make_step()

    with pytest.raises(requests.HTTPError):
        handle(ctx, step)


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "ftp://ftp.example.com/file",
        "data:text/plain,hello",
        "javascript:alert(1)",
    ],
)
def test_handle_rejects_non_http_urls(tmp_path: Path, bad_url: str) -> None:
    ctx = _make_context(tmp_path, source=bad_url)
    step = _make_step()

    with pytest.raises(RuntimeError, match="URL scheme"):
        handle(ctx, step)
