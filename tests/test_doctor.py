from __future__ import annotations

from pathlib import Path

from solus.modules.spec import Dependency, ModuleSpec
from solus.config import BinaryConfig, Config, OllamaConfig, PathsConfig, PromptsConfig, WhisperConfig
from solus.doctor import run_doctor
from solus.workflows.models import Step, Workflow
from solus.workflows.registry import StepRegistry


def _config(tmp_path: Path) -> Config:
    whisper_cli = tmp_path / "whisper-cli"
    whisper_model = tmp_path / "model.bin"
    whisper_cli.write_text("", encoding="utf-8")
    whisper_model.write_text("", encoding="utf-8")
    return Config(
        paths=PathsConfig(cache_dir=tmp_path / "cache"),
        whisper=WhisperConfig(cli_path=whisper_cli, model_path=whisper_model, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="qwen3:8b", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        config_path=tmp_path / "config.toml",
        config_exists=True,
    )


def test_run_doctor_returns_failure_when_module_dependency_check_sets_missing(monkeypatch, tmp_path: Path) -> None:
    cfg = _config(tmp_path)

    class _Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr("solus.doctor.ensure_dir", lambda path: path)
    monkeypatch.setattr("solus.doctor._find_binary", lambda _binary: "/bin/true")
    monkeypatch.setattr("solus.doctor._check_binary_runs", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("solus.doctor.requests.get", lambda *_args, **_kwargs: _Resp())
    monkeypatch.setattr("solus.doctor.list_workflows", lambda **_kwargs: ([], []))

    def _mark_missing(missing_required_ref: list[bool], external_dir=None) -> None:
        del external_dir
        missing_required_ref[0] = True

    monkeypatch.setattr("solus.doctor._check_module_dependencies", _mark_missing)

    assert run_doctor(cfg) == 1


def test_run_doctor_workflow_scope_skips_audio_checks(monkeypatch, tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    workflow = Workflow(
        name="webpage_summary",
        description="",
        steps=[
            Step(name="fetch", type="input.webpage_fetch", config={}),
            Step(name="summarize", type="ai.llm_summarize", config={}),
        ],
    )
    registry = StepRegistry()
    registry.register(
        "input.webpage_fetch",
        lambda ctx, step: ctx,
        spec=ModuleSpec(
            name="webpage_fetch",
            version="0.1.0",
            category="input",
            description="",
            handler=lambda ctx, step: ctx,
            dependencies=(),
        ),
    )
    registry.register(
        "ai.llm_summarize",
        lambda ctx, step: ctx,
        spec=ModuleSpec(
            name="llm_summarize",
            version="0.1.0",
            category="ai",
            description="",
            handler=lambda ctx, step: ctx,
            dependencies=(Dependency(name="ollama", kind="service"),),
        ),
    )

    monkeypatch.setattr("solus.doctor.ensure_dir", lambda path: path)
    monkeypatch.setattr("solus.doctor.list_workflows", lambda **_kwargs: ([], []))
    monkeypatch.setattr("solus.doctor.load_workflow", lambda *_args, **_kwargs: workflow)
    monkeypatch.setattr("solus.doctor.build_registry", lambda **_kwargs: registry)
    monkeypatch.setattr("solus.doctor._check_ollama", lambda _config: False)
    monkeypatch.setattr("solus.doctor._check_module_dependencies", lambda **_kwargs: None)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("audio dependency check should not run for webpage_summary workflow scope")

    monkeypatch.setattr("solus.doctor._check_yt_dlp", _unexpected)
    monkeypatch.setattr("solus.doctor._check_ffmpeg", _unexpected)
    monkeypatch.setattr("solus.doctor._check_whisper", _unexpected)

    assert run_doctor(cfg, workflow_name="webpage_summary") == 0
