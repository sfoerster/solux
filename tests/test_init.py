"""Tests for ``solux init`` command."""

from __future__ import annotations

from pathlib import Path

from solux.cli.init import cmd_init


def test_init_creates_config_and_workflow(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.toml"
    workflows_dir = tmp_path / "workflows.d"

    monkeypatch.setattr("solux.cli.init.ensure_config_file", lambda: (config_path, True))

    # Minimal config that load_config can return
    from solux.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        WhisperConfig,
    )

    cfg = Config(
        paths=PathsConfig(cache_dir=tmp_path / "cache"),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="qwen3:8b", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        config_path=config_path,
        config_exists=True,
        workflows_dir=workflows_dir,
    )
    monkeypatch.setattr("solux.cli.init.load_config", lambda _path: cfg)
    monkeypatch.setattr("solux.cli.init.run_doctor", lambda *_a, **_kw: 0)

    # Mock Ollama as reachable
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr("solux.cli.init.requests.get", lambda *_a, **_kw: _Resp())

    ret = cmd_init()
    assert ret == 0

    # Workflow file should be scaffolded
    scaffold = workflows_dir / "my_summarizer.yaml"
    assert scaffold.exists()
    content = scaffold.read_text()
    assert "my_summarizer" in content
    assert "input.webpage_fetch" in content
    assert "transform.text_clean" in content
    assert "ai.llm_summarize" in content
    assert "output.file_write" in content

    captured = capsys.readouterr()
    assert "Created config" in captured.out
    assert "Next steps" in captured.out


def test_init_idempotent_does_not_overwrite(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    workflows_dir = tmp_path / "workflows.d"
    workflows_dir.mkdir()
    scaffold = workflows_dir / "my_summarizer.yaml"
    scaffold.write_text("existing content", encoding="utf-8")

    monkeypatch.setattr("solux.cli.init.ensure_config_file", lambda: (config_path, False))

    from solux.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        WhisperConfig,
    )

    cfg = Config(
        paths=PathsConfig(cache_dir=tmp_path / "cache"),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="qwen3:8b", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        config_path=config_path,
        config_exists=True,
        workflows_dir=workflows_dir,
    )
    monkeypatch.setattr("solux.cli.init.load_config", lambda _path: cfg)
    monkeypatch.setattr("solux.cli.init.run_doctor", lambda *_a, **_kw: 0)

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr("solux.cli.init.requests.get", lambda *_a, **_kw: _Resp())

    ret = cmd_init()
    assert ret == 0

    # File should NOT be overwritten
    assert scaffold.read_text() == "existing content"


def test_init_ollama_unreachable_shows_install_hint(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.toml"
    workflows_dir = tmp_path / "workflows.d"

    monkeypatch.setattr("solux.cli.init.ensure_config_file", lambda: (config_path, True))

    from solux.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        WhisperConfig,
    )

    cfg = Config(
        paths=PathsConfig(cache_dir=tmp_path / "cache"),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="qwen3:8b", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        config_path=config_path,
        config_exists=True,
        workflows_dir=workflows_dir,
    )
    monkeypatch.setattr("solux.cli.init.load_config", lambda _path: cfg)
    monkeypatch.setattr("solux.cli.init.run_doctor", lambda *_a, **_kw: 0)

    import requests as req

    monkeypatch.setattr("solux.cli.init.requests.get", lambda *_a, **_kw: (_ for _ in ()).throw(req.ConnectionError()))

    ret = cmd_init()
    assert ret == 0

    captured = capsys.readouterr()
    assert "not reachable" in captured.out
    assert "ollama serve" in captured.out
