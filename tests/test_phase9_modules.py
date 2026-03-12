"""Tests for Phase 9: new module matrix."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from solus.modules.discovery import discover_modules
from solus.workflows.models import Context, Step
from solus.workflows.registry import StepRegistry


def _make_ctx(data: dict[str, Any] | None = None, source: str = "test-source") -> Context:
    from solus.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        SecurityConfig,
        WhisperConfig,
    )
    import tempfile

    config = Config(
        paths=PathsConfig(cache_dir=Path(tempfile.mkdtemp())),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="test", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        security=SecurityConfig(),
        config_path=Path("/tmp/test.toml"),
        config_exists=False,
    )
    return Context(
        source=source,
        source_id="test-src-id",
        data=dict(data or {}),
        config=config,
        logger=logging.getLogger("test"),
    )


def _make_step(step_type: str, config: dict | None = None) -> Step:
    return Step(name="test", type=step_type, config=dict(config or {}))


# --- text_split ---


def test_text_split_paragraph() -> None:
    from solus.modules.transform.text_split import handle, MODULE

    ctx = _make_ctx({"input_text": "Para one.\n\nPara two.\n\nPara three."})
    step = _make_step("transform.text_split", {"method": "paragraph"})
    result = handle(ctx, step)
    chunks = result.data["chunks"]
    assert isinstance(chunks, list)
    assert len(chunks) >= 2


def test_text_split_sentence() -> None:
    from solus.modules.transform.text_split import handle

    ctx = _make_ctx({"input_text": "Hello world. This is a test. And one more."})
    step = _make_step("transform.text_split", {"method": "sentence"})
    result = handle(ctx, step)
    assert len(result.data["chunks"]) >= 2


def test_text_split_fixed() -> None:
    from solus.modules.transform.text_split import handle

    text = "A" * 500
    ctx = _make_ctx({"input_text": text})
    step = _make_step("transform.text_split", {"method": "fixed", "chunk_size": 200, "overlap": 50})
    result = handle(ctx, step)
    chunks = result.data["chunks"]
    assert len(chunks) >= 2
    assert all(len(c) <= 200 for c in chunks)


def test_text_split_fixed_clamps_overlap_to_avoid_infinite_loop() -> None:
    from solus.modules.transform.text_split import handle

    text = "A" * 24
    ctx = _make_ctx({"input_text": text})
    step = _make_step(
        "transform.text_split",
        {"method": "fixed", "chunk_size": 8, "overlap": 8},
    )

    result = handle(ctx, step)
    chunks = result.data["chunks"]
    assert chunks
    assert len(chunks) <= len(text)
    assert all(len(c) <= 8 for c in chunks)


def test_text_split_custom_keys() -> None:
    from solus.modules.transform.text_split import handle

    ctx = _make_ctx({"my_text": "Para A.\n\nPara B."})
    step = _make_step("transform.text_split", {"input_key": "my_text", "output_key": "my_chunks"})
    result = handle(ctx, step)
    assert "my_chunks" in result.data


def test_text_split_missing_input_raises() -> None:
    from solus.modules.transform.text_split import handle

    ctx = _make_ctx({})
    step = _make_step("transform.text_split")
    with pytest.raises(RuntimeError, match="missing"):
        handle(ctx, step)


def test_text_split_module_spec() -> None:
    from solus.modules.transform.text_split import MODULE

    assert MODULE.name == "text_split"
    assert MODULE.category == "transform"
    assert any(w.key == "chunks" for w in MODULE.writes)


# --- text_clean ---


def test_text_clean_strips_html() -> None:
    from solus.modules.transform.text_clean import handle

    ctx = _make_ctx({"input_text": "<p>Hello <b>world</b></p>"})
    step = _make_step("transform.text_clean", {"strip_html": True})
    result = handle(ctx, step)
    assert "<p>" not in result.data["cleaned_text"]
    assert "Hello" in result.data["cleaned_text"]


def test_text_clean_no_strip_html() -> None:
    from solus.modules.transform.text_clean import handle

    ctx = _make_ctx({"input_text": "<p>Hello</p>"})
    step = _make_step("transform.text_clean", {"strip_html": False, "normalize_whitespace": False})
    result = handle(ctx, step)
    assert "<p>" in result.data["cleaned_text"]


def test_text_clean_normalize_whitespace() -> None:
    from solus.modules.transform.text_clean import handle

    ctx = _make_ctx({"input_text": "hello   world\n\n\n\nextra"})
    step = _make_step("transform.text_clean", {"strip_html": False, "normalize_whitespace": True})
    result = handle(ctx, step)
    assert "   " not in result.data["cleaned_text"]
    assert "\n\n\n" not in result.data["cleaned_text"]


def test_text_clean_max_chars() -> None:
    from solus.modules.transform.text_clean import handle

    ctx = _make_ctx({"input_text": "A" * 1000})
    step = _make_step("transform.text_clean", {"strip_html": False, "normalize_whitespace": False, "max_chars": 100})
    result = handle(ctx, step)
    assert len(result.data["cleaned_text"]) <= 100


def test_text_clean_module_spec() -> None:
    from solus.modules.transform.text_clean import MODULE

    assert MODULE.name == "text_clean"
    assert MODULE.category == "transform"
    assert any(w.key == "cleaned_text" for w in MODULE.writes)


# --- metadata_extract ---


def test_metadata_extract_from_source(tmp_path: Path) -> None:
    from solus.modules.transform.metadata_extract import handle

    test_file = tmp_path / "test.txt"
    test_file.write_text("hello", encoding="utf-8")
    ctx = _make_ctx(source=str(test_file))
    step = _make_step("transform.metadata_extract")
    result = handle(ctx, step)
    meta = result.data["file_metadata"]
    assert isinstance(meta, dict)
    assert "size_bytes" in meta
    assert meta["filename"] == "test.txt"
    assert meta["extension"] == ".txt"


def test_metadata_extract_custom_key(tmp_path: Path) -> None:
    from solus.modules.transform.metadata_extract import handle

    test_file = tmp_path / "report.pdf"
    test_file.write_bytes(b"%PDF-1.4")
    ctx = _make_ctx({"my_path": str(test_file)})
    step = _make_step("transform.metadata_extract", {"input_key": "my_path", "output_key": "my_meta"})
    result = handle(ctx, step)
    assert "my_meta" in result.data


def test_metadata_extract_module_spec() -> None:
    from solus.modules.transform.metadata_extract import MODULE

    assert MODULE.name == "metadata_extract"
    assert MODULE.category == "transform"
    assert any(w.key == "file_metadata" for w in MODULE.writes)


# --- OCR module (soft-import) ---


def test_ocr_module_spec() -> None:
    from solus.modules.transform.ocr import MODULE

    assert MODULE.name == "ocr"
    assert MODULE.category == "transform"
    assert any(w.key == "ocr_text" for w in MODULE.writes)


def test_ocr_raises_without_pytesseract(tmp_path: Path) -> None:
    from solus.modules.transform.ocr import handle

    test_file = tmp_path / "img.png"
    test_file.write_bytes(b"\x89PNG")
    ctx = _make_ctx(source=str(test_file))
    step = _make_step("transform.ocr")
    import sys

    # Simulate pytesseract not being installed
    with patch.dict(sys.modules, {"pytesseract": None, "PIL": None, "PIL.Image": None}):
        with pytest.raises((RuntimeError, ImportError)):
            handle(ctx, step)


# --- vector_store ---


def test_vector_store_module_spec() -> None:
    from solus.modules.output.vector_store import MODULE

    assert MODULE.name == "vector_store"
    assert MODULE.category == "output"
    assert MODULE.safety == "trusted_only"
    assert any(w.key == "vector_store_id" for w in MODULE.writes)


def test_vector_store_raises_without_chromadb() -> None:
    from solus.modules.output.vector_store import handle
    import sys

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step("output.vector_store")
    with patch.dict(sys.modules, {"chromadb": None}):
        with pytest.raises((RuntimeError, ImportError)):
            handle(ctx, step)


# --- email_send ---


def test_email_send_module_spec() -> None:
    from solus.modules.output.email_send import MODULE

    assert MODULE.name == "email_send"
    assert MODULE.category == "output"
    assert MODULE.safety == "trusted_only"
    assert MODULE.network is True
    assert any(w.key == "email_sent" for w in MODULE.writes)


def test_email_send_missing_host_raises() -> None:
    from solus.modules.output.email_send import handle

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step("output.email_send")
    with pytest.raises(RuntimeError, match="smtp_host"):
        handle(ctx, step)


def test_email_send_missing_to_addr_raises() -> None:
    from solus.modules.output.email_send import handle

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step("output.email_send", {"smtp_host": "mail.example.com"})
    with pytest.raises(RuntimeError, match="to_addr"):
        handle(ctx, step)


def test_email_send_env_interpolation() -> None:
    from solus.modules._helpers import interpolate_env
    import os

    os.environ["TEST_SMTP_PASS"] = "secret123"
    result = interpolate_env("${env:TEST_SMTP_PASS}")
    assert result == "secret123"
    del os.environ["TEST_SMTP_PASS"]


def test_email_send_subject_template_handles_display_name_key_collision() -> None:
    from solus.modules.output.email_send import handle

    ctx = _make_ctx({"output_text": "body", "display_name": "Episode A"})
    step = _make_step(
        "output.email_send",
        {
            "smtp_host": "mail.example.com",
            "to_addr": "to@example.com",
            "subject_template": "Solus: {display_name}",
        },
    )

    mock_smtp = MagicMock()
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server
    with patch("solus.modules.output.email_send.smtplib.SMTP", mock_smtp):
        result = handle(ctx, step)

    assert result.data["email_sent"] is True
    assert mock_server.send_message.called


# --- obsidian_vault ---


def test_obsidian_vault_write(tmp_path: Path) -> None:
    from solus.modules.output.obsidian_vault import handle

    vault = tmp_path / "vault"
    ctx = _make_ctx({"output_text": "# Hello\nBody text", "display_name": "My Note"})
    step = _make_step(
        "output.obsidian_vault",
        {
            "vault_path": str(vault),
            "folder": "notes",
            "tags": ["ai", "solus"],
        },
    )
    result = handle(ctx, step)
    note_path = Path(result.data["obsidian_note_path"])
    assert note_path.exists()
    content = note_path.read_text(encoding="utf-8")
    assert "---" in content
    assert "source:" in content
    assert "Hello" in content


def test_obsidian_vault_no_overwrite(tmp_path: Path) -> None:
    from solus.modules.output.obsidian_vault import handle

    vault = tmp_path / "vault"
    ctx = _make_ctx({"output_text": "Original", "display_name": "Note"})
    step = _make_step("output.obsidian_vault", {"vault_path": str(vault), "overwrite": False})
    result = handle(ctx, step)
    original_path = result.data["obsidian_note_path"]
    # Second call should not overwrite
    ctx2 = _make_ctx({"output_text": "Updated", "display_name": "Note"})
    result2 = handle(ctx2, step)
    content = Path(result2.data["obsidian_note_path"]).read_text(encoding="utf-8")
    assert "Updated" not in content  # Not overwritten


def test_obsidian_vault_module_spec() -> None:
    from solus.modules.output.obsidian_vault import MODULE

    assert MODULE.name == "obsidian_vault"
    assert MODULE.safety == "trusted_only"
    assert any(w.key == "obsidian_note_path" for w in MODULE.writes)


def test_obsidian_vault_missing_path_raises() -> None:
    from solus.modules.output.obsidian_vault import handle

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step("output.obsidian_vault", {"vault_path": "   "})
    with pytest.raises(RuntimeError, match="vault_path"):
        handle(ctx, step)


# --- slack_notify ---


def test_slack_notify_module_spec() -> None:
    from solus.modules.output.slack_notify import MODULE

    assert MODULE.name == "slack_notify"
    assert MODULE.safety == "trusted_only"
    assert MODULE.network is True
    assert any(w.key == "slack_status_code" for w in MODULE.writes)


def test_slack_notify_missing_url_raises() -> None:
    from solus.modules.output.slack_notify import handle

    ctx = _make_ctx({"output_text": "hi"})
    step = _make_step("output.slack_notify")
    with pytest.raises(RuntimeError, match="webhook_url"):
        handle(ctx, step)


def test_slack_notify_posts_to_webhook() -> None:
    from solus.modules.output.slack_notify import handle

    ctx = _make_ctx({"output_text": "Hello Slack!"})
    step = _make_step("output.slack_notify", {"webhook_url": "https://hooks.slack.com/test"})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("solus.modules.output.slack_notify.requests.post", return_value=mock_resp) as mock_post:
        result = handle(ctx, step)
    assert result.data["slack_status_code"] == 200
    mock_post.assert_called_once()


def test_slack_notify_logs_redacted_webhook_url() -> None:
    from solus.modules.output.slack_notify import handle

    ctx = _make_ctx({"output_text": "Hello Slack!"})
    ctx.logger = MagicMock()
    step = _make_step(
        "output.slack_notify",
        {"webhook_url": "https://hooks.slack.com/services/TOKEN/SECRET"},
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    with patch("solus.modules.output.slack_notify.requests.post", return_value=mock_resp):
        handle(ctx, step)

    ctx.logger.info.assert_any_call("slack_notify: POST %s -> %d", "https://hooks.slack.com", 200)


def test_slack_notify_raises_on_non_2xx_by_default() -> None:
    from solus.modules.output.slack_notify import handle

    ctx = _make_ctx({"output_text": "Hello Slack!"})
    step = _make_step("output.slack_notify", {"webhook_url": "https://hooks.slack.com/test"})
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.ok = False
    mock_resp.text = "server error"

    with patch("solus.modules.output.slack_notify.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="server returned 500"):
            handle(ctx, step)


def test_slack_notify_template_handles_nested_context_data() -> None:
    from solus.modules.output.slack_notify import handle

    ctx = _make_ctx(
        {
            "output_text": "fallback",
            "sentiment": {"label": "positive", "score": 0.92},
            "display_name": "Article A",
        }
    )
    step = _make_step(
        "output.slack_notify",
        {
            "webhook_url": "https://hooks.slack.com/test",
            "message_template": "Sentiment: {sentiment[label]} ({sentiment[score]:.2f})",
        },
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("solus.modules.output.slack_notify.requests.post", return_value=mock_resp) as mock_post:
        result = handle(ctx, step)

    payload = mock_post.call_args.kwargs["data"]
    assert "Sentiment: positive (0.92)" in payload
    assert result.data["slack_status_code"] == 200


# --- email_inbox ---


def test_email_inbox_module_spec() -> None:
    from solus.modules.input.email_inbox import MODULE

    assert MODULE.name == "email_inbox"
    assert MODULE.safety == "trusted_only"
    assert MODULE.network is True
    assert any(w.key == "messages" for w in MODULE.writes)


def test_email_inbox_missing_host_raises() -> None:
    from solus.modules.input.email_inbox import handle

    ctx = _make_ctx()
    step = _make_step("input.email_inbox")
    with pytest.raises(RuntimeError, match="host"):
        handle(ctx, step)


def test_email_inbox_missing_credentials_raises() -> None:
    from solus.modules.input.email_inbox import handle

    ctx = _make_ctx()
    step = _make_step("input.email_inbox", {"host": "imap.example.com"})
    with pytest.raises(RuntimeError, match="username"):
        handle(ctx, step)


# --- youtube_playlist ---


def test_youtube_playlist_module_spec() -> None:
    from solus.modules.input.youtube_playlist import MODULE

    assert MODULE.name == "youtube_playlist"
    assert MODULE.category == "input"
    assert MODULE.network is True
    assert any(w.key == "video_urls" for w in MODULE.writes)


def test_youtube_playlist_uses_yt_dlp() -> None:
    from solus.modules.input.youtube_playlist import handle

    ctx = _make_ctx(source="https://www.youtube.com/playlist?list=PLtest")
    step = _make_step("input.youtube_playlist", {"limit": 5})
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""
    mock_result.stdout = (
        '{"url": "https://www.youtube.com/watch?v=abc", "playlist_title": "Test Playlist"}\n'
        '{"url": "https://www.youtube.com/watch?v=def"}\n'
    )
    with patch("solus.modules.input.youtube_playlist.subprocess.run", return_value=mock_result):
        result = handle(ctx, step)
    assert result.data["video_urls"] == [
        "https://www.youtube.com/watch?v=abc",
        "https://www.youtube.com/watch?v=def",
    ]
    assert result.data["playlist_title"] == "Test Playlist"


def test_youtube_playlist_raises_on_nonzero_return_code() -> None:
    from solus.modules.input.youtube_playlist import handle

    ctx = _make_ctx(source="https://www.youtube.com/playlist?list=PLtest")
    step = _make_step("input.youtube_playlist", {"limit": 5})
    mock_result = MagicMock(returncode=1, stdout="", stderr="yt-dlp error")

    with patch("solus.modules.input.youtube_playlist.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="returned 1"):
            handle(ctx, step)


# --- s3_watcher ---


def test_s3_watcher_module_spec() -> None:
    from solus.modules.input.s3_watcher import MODULE

    assert MODULE.name == "s3_watcher"
    assert MODULE.safety == "trusted_only"
    assert MODULE.network is True
    assert any(w.key == "s3_objects" for w in MODULE.writes)


def test_s3_watcher_missing_bucket_raises() -> None:
    from solus.modules.input.s3_watcher import handle
    import sys

    boto3_mock = MagicMock()
    with patch.dict(sys.modules, {"boto3": boto3_mock}):
        ctx = _make_ctx()
        step = _make_step("input.s3_watcher")
        with pytest.raises(RuntimeError, match="bucket"):
            handle(ctx, step)


def test_s3_watcher_raises_without_boto3() -> None:
    from solus.modules.input.s3_watcher import handle
    import sys

    with patch.dict(sys.modules, {"boto3": None}):
        ctx = _make_ctx()
        step = _make_step("input.s3_watcher", {"bucket": "my-bucket"})
        with pytest.raises((RuntimeError, ImportError)):
            handle(ctx, step)


# --- llm_sentiment ---


def test_llm_sentiment_module_spec() -> None:
    from solus.modules.ai.llm_sentiment import MODULE

    assert MODULE.name == "llm_sentiment"
    assert MODULE.category == "ai"
    assert MODULE.network is True
    assert any(w.key == "sentiment" for w in MODULE.writes)


def test_llm_sentiment_missing_input_raises() -> None:
    from solus.modules.ai.llm_sentiment import handle

    ctx = _make_ctx()
    step = _make_step("ai.llm_sentiment")
    with patch("solus.modules.ai.llm_sentiment.call_ollama_chat", return_value="positive"):
        with pytest.raises(RuntimeError, match="missing"):
            handle(ctx, step)


def test_llm_sentiment_pos_neg_neu() -> None:
    from solus.modules.ai.llm_sentiment import handle

    ctx = _make_ctx({"input_text": "I love this product!"})
    step = _make_step("ai.llm_sentiment", {"scale": "pos_neg_neu"})
    mock_response = '{"label": "positive", "score": 0.92, "explanation": "Very positive tone."}'
    with patch("solus.modules.ai.llm_sentiment.call_ollama_chat", return_value=mock_response):
        result = handle(ctx, step)
    sentiment = result.data["sentiment"]
    assert isinstance(sentiment, dict)
    assert sentiment.get("label") == "positive"
    assert sentiment.get("score") == pytest.approx(0.92)


def test_llm_sentiment_custom_keys() -> None:
    from solus.modules.ai.llm_sentiment import handle

    ctx = _make_ctx({"my_text": "Bad service!"})
    step = _make_step("ai.llm_sentiment", {"input_key": "my_text", "output_key": "my_sentiment"})
    with patch("solus.modules.ai.llm_sentiment.call_ollama_chat", return_value='{"label": "negative", "score": 0.1}'):
        result = handle(ctx, step)
    assert "my_sentiment" in result.data


# --- secrets interpolation in loader ---


def test_loader_secrets_interpolation() -> None:
    import os
    from solus.workflows.loader import _interpolate_secrets

    os.environ["MY_SECRET"] = "s3cr3t"
    result = _interpolate_secrets("prefix-${env:MY_SECRET}-suffix")
    assert result == "prefix-s3cr3t-suffix"
    del os.environ["MY_SECRET"]


def test_loader_secrets_interpolation_dict() -> None:
    from solus.workflows.loader import _interpolate_secrets
    import os

    os.environ["API_KEY"] = "key123"
    result = _interpolate_secrets({"password": "${env:API_KEY}", "host": "localhost"})
    assert result["password"] == "key123"
    assert result["host"] == "localhost"
    del os.environ["API_KEY"]


def test_loader_secrets_missing_env_empty_string() -> None:
    from solus.workflows.loader import _interpolate_secrets

    result = _interpolate_secrets("${env:DOES_NOT_EXIST_XYZ123}")
    assert result == ""


def test_loader_parses_timeout_field() -> None:
    from solus.workflows.loader import _parse_step

    raw = {"name": "mystep", "type": "ai.llm_prompt", "config": {}, "timeout": 30}
    step = _parse_step(raw, 0)
    assert step.timeout_seconds == 30


def test_loader_invalid_timeout_raises() -> None:
    from solus.workflows.loader import WorkflowLoadError, _parse_step

    raw = {"name": "s", "type": "ai.llm_prompt", "config": {}, "timeout": "not-an-int"}
    with pytest.raises(WorkflowLoadError):
        _parse_step(raw, 0)


def test_loader_negative_timeout_raises() -> None:
    from solus.workflows.loader import WorkflowLoadError, _parse_step

    raw = {"name": "s", "type": "ai.llm_prompt", "config": {}, "timeout": -5}
    with pytest.raises(WorkflowLoadError, match="positive integer"):
        _parse_step(raw, 0)


def test_loader_zero_timeout_raises() -> None:
    from solus.workflows.loader import WorkflowLoadError, _parse_step

    raw = {"name": "s", "type": "ai.llm_prompt", "config": {}, "timeout": 0}
    with pytest.raises(WorkflowLoadError, match="positive integer"):
        _parse_step(raw, 0)


def test_workflow_to_dict_preserves_timeout_field() -> None:
    from solus.workflows.loader import workflow_to_dict
    from solus.workflows.models import Workflow

    wf = Workflow(
        name="wf",
        description="",
        steps=[Step(name="slow", type="ai.llm_prompt", config={}, timeout_seconds=45)],
    )
    payload = workflow_to_dict(wf)
    assert payload["steps"][0]["timeout"] == 45


# --- Module discovery ---


def test_phase9_modules_are_discovered() -> None:
    specs = discover_modules()
    names = {s.name for s in specs}
    new_modules = {
        "text_split",
        "ocr",
        "text_clean",
        "metadata_extract",
        "vector_store",
        "email_send",
        "obsidian_vault",
        "slack_notify",
        "email_inbox",
        "youtube_playlist",
        "s3_watcher",
        "llm_sentiment",
    }
    for name in new_modules:
        assert name in names, f"Module '{name}' not found in discovery"


def test_vinsium_node_discovered() -> None:
    specs = discover_modules()
    names = {s.name for s in specs}
    assert "vinsium_node" in names
