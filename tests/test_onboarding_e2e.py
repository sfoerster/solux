"""End-to-end smoke tests for Phase 1 onboarding flow: init -> dry-run -> doctor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from solux.cli import main


@pytest.fixture()
def clean_env(tmp_path: Path, monkeypatch):
    """Set up a clean HOME-like environment for the onboarding flow."""
    config_dir = tmp_path / ".config" / "solux"
    cache_dir = tmp_path / ".local" / "share" / "solux"
    config_path = config_dir / "config.toml"
    workflows_dir = config_dir / "workflows.d"

    # Point solux at our temp dirs
    monkeypatch.setattr("solux.config.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("solux.config.DEFAULT_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr("solux.config.DEFAULT_WORKFLOWS_DIR", workflows_dir)
    monkeypatch.setattr("solux.config.DEFAULT_MODULES_DIR", config_dir / "modules.d")
    monkeypatch.setattr("solux.config.DEFAULT_TRIGGERS_DIR", config_dir / "triggers.d")

    # Suppress color in test output
    monkeypatch.setenv("NO_COLOR", "1")

    return {
        "config_path": config_path,
        "config_dir": config_dir,
        "cache_dir": cache_dir,
        "workflows_dir": workflows_dir,
    }


def test_init_then_dryrun_then_doctor(clean_env, monkeypatch, capsys):
    """Full onboarding: init -> dry-run -> doctor, all with mocked Ollama."""
    import requests

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr("requests.get", lambda *_a, **_kw: _Resp())
    monkeypatch.setattr("solux.config.requests.get", lambda *_a, **_kw: _Resp())

    # 1. solux init
    ret = main(["init"])
    assert ret == 0

    assert clean_env["config_path"].exists()
    scaffold = clean_env["workflows_dir"] / "my_summarizer.yaml"
    assert scaffold.exists()

    captured = capsys.readouterr()
    assert "Next steps" in captured.out

    # 2. solux run --dry-run --workflow webpage_summary https://example.com
    ret = main(["run", "--dry-run", "--workflow", "webpage_summary", "https://example.com"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Workflow: webpage_summary" in captured.out
    assert "Validation: OK" in captured.out

    # 3. solux doctor --workflow webpage_summary
    monkeypatch.setattr("solux.doctor.requests.get", lambda *_a, **_kw: _Resp())
    ret = main(["doctor", "--workflow", "webpage_summary"])
    assert ret == 0


def test_init_idempotent(clean_env, monkeypatch, capsys):
    """Running init twice does not overwrite existing files."""
    import requests

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr("requests.get", lambda *_a, **_kw: _Resp())
    monkeypatch.setattr("solux.config.requests.get", lambda *_a, **_kw: _Resp())
    monkeypatch.setattr("solux.doctor.requests.get", lambda *_a, **_kw: _Resp())

    # First run
    main(["init"])
    scaffold = clean_env["workflows_dir"] / "my_summarizer.yaml"
    first_content = scaffold.read_text()

    # Modify the scaffold to prove idempotency
    scaffold.write_text("modified", encoding="utf-8")

    # Second run
    capsys.readouterr()  # clear
    main(["init"])
    assert scaffold.read_text() == "modified"

    captured = capsys.readouterr()
    assert "already exists" in captured.out


def test_default_workflow_is_webpage_summary():
    """After Phase 1, the default workflow should be webpage_summary."""
    from solux.config import DEFAULT_UI_WORKFLOW

    assert DEFAULT_UI_WORKFLOW == "webpage_summary"


def test_examples_shorthand(clean_env, monkeypatch, capsys):
    """``solux examples`` should produce the same output as ``solux workflows examples``."""
    ret = main(["examples"])
    examples_out = capsys.readouterr().out

    ret2 = main(["workflows", "examples"])
    workflows_examples_out = capsys.readouterr().out

    assert ret == ret2
    assert examples_out == workflows_examples_out


def test_doctor_scoped_default(clean_env, monkeypatch, capsys):
    """Default doctor (no --all) should not check whisper/yt-dlp/ffmpeg for webpage_summary-only setup."""
    import requests

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr("requests.get", lambda *_a, **_kw: _Resp())
    monkeypatch.setattr("solux.config.requests.get", lambda *_a, **_kw: _Resp())
    monkeypatch.setattr("solux.doctor.requests.get", lambda *_a, **_kw: _Resp())

    # Init first to set up config
    main(["init"])
    capsys.readouterr()

    # Doctor should pass without audio stack
    ret = main(["doctor"])
    captured = capsys.readouterr()
    # Should NOT mention yt-dlp or whisper when only webpage_summary is configured
    assert "yt-dlp" not in captured.out
    assert "whisper" not in captured.out


def test_doctor_fix_flag(clean_env, monkeypatch, capsys):
    """``solux doctor --fix`` shows Fix: prefix."""
    import requests

    # Make Ollama unreachable to trigger a warning
    monkeypatch.setattr(
        "solux.doctor.requests.get",
        lambda *_a, **_kw: (_ for _ in ()).throw(requests.ConnectionError()),
    )

    # Need config to exist
    main_ret = main(["init"])
    capsys.readouterr()

    # Force Ollama check via --all
    monkeypatch.setattr("requests.get", lambda *_a, **_kw: (_ for _ in ()).throw(requests.ConnectionError()))
    monkeypatch.setattr(
        "solux.config.requests.get", lambda *_a, **_kw: (_ for _ in ()).throw(requests.ConnectionError())
    )
    ret = main(["doctor", "--fix", "--workflow", "webpage_summary"])
    captured = capsys.readouterr()
    assert "Fix:" in captured.out


@pytest.mark.skipif(
    os.environ.get("SOLUX_E2E") != "1",
    reason="Set SOLUX_E2E=1 to run real end-to-end test with Ollama",
)
def test_real_onboarding_under_60s(clean_env, monkeypatch, capsys):
    """Real end-to-end: init + doctor + real workflow run with actual Ollama, under 60s."""
    import time

    start = time.monotonic()

    ret = main(["init"])
    assert ret == 0

    ret = main(["doctor", "--workflow", "webpage_summary"])
    # Don't assert == 0 since Ollama model might not be pulled

    ret = main(["run", "--workflow", "webpage_summary", "https://example.com"])
    assert ret == 0

    elapsed = time.monotonic() - start
    assert elapsed < 60, f"Onboarding took {elapsed:.1f}s, exceeds 60s target"
