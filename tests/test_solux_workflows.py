from __future__ import annotations

from pathlib import Path

from solux.cli import main, parse_args
from solux.config import load_config
from solux.queueing import enqueue_jobs, read_jobs
from solux.workflows.loader import list_workflows, load_workflow


def test_solux_parse_args_shorthand_uses_run_and_config_default_workflow() -> None:
    args = parse_args(["episode.mp3"])
    assert args.command == "run"
    assert args.source == "episode.mp3"
    assert args.workflow is None


def test_solux_parse_args_workflows_show() -> None:
    args = parse_args(["workflows", "show", "audio_summary"])
    assert args.command == "workflows"
    assert args.workflows_action == "show"
    assert args.name == "audio_summary"


def test_builtin_audio_summary_workflow_loads() -> None:
    wf = load_workflow("audio_summary")
    assert wf.name == "audio_summary"
    assert [step.type for step in wf.steps] == [
        "input.source_fetch",
        "transform.audio_normalize",
        "ai.whisper_transcribe",
        "ai.llm_summarize",
    ]


def test_builtin_webpage_summary_workflow_loads() -> None:
    wf = load_workflow("webpage_summary")
    assert wf.name == "webpage_summary"
    assert [step.type for step in wf.steps] == [
        "input.webpage_fetch",
        "ai.llm_summarize",
        "output.file_write",
    ]


def test_enqueue_jobs_persists_workflow_name_and_params(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    enqueue_jobs(
        cache_dir,
        ["ep.mp3"],
        workflow_name="audio_summary",
        params={"mode": "tldr", "format": "json", "timestamps": True},
    )
    jobs = read_jobs(cache_dir)
    assert len(jobs) == 1
    assert jobs[0]["workflow_name"] == "audio_summary"
    assert jobs[0]["params"]["mode"] == "tldr"
    assert jobs[0]["params"]["format"] == "json"
    assert jobs[0]["params"]["timestamps"] is True


def test_workflows_validate_command_audio_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = main(["workflows", "validate", "audio_summary"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Validation: OK" in captured.out


def test_workflows_validate_command_unknown(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = main(["workflows", "validate", "does_not_exist"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "not found" in captured.err.lower()


def test_yaml_workflow_loads_from_custom_dir(tmp_path: Path) -> None:
    yaml_content = """\
name: test_custom
description: A test workflow loaded from YAML.
steps:
  - name: fetch
    type: input.source_fetch
    config: {}
"""
    wf_file = tmp_path / "test_custom.yaml"
    wf_file.write_text(yaml_content, encoding="utf-8")

    wf = load_workflow("test_custom", workflow_dir=tmp_path)
    assert wf.name == "test_custom"
    assert wf.description == "A test workflow loaded from YAML."
    assert len(wf.steps) == 1
    assert wf.steps[0].type == "input.source_fetch"


def test_list_workflows_does_not_warn_for_missing_env_by_default(caplog, tmp_path: Path) -> None:
    workflow_path = tmp_path / "with_secret.yaml"
    workflow_path.write_text(
        """\
name: with_secret
description: Test interpolation warnings
steps:
  - name: notify
    type: output.slack_notify
    config:
      webhook_url: "${env:MISSING_WEBHOOK_URL}"
""",
        encoding="utf-8",
    )

    caplog.set_level("WARNING")
    caplog.clear()
    workflows, invalid = list_workflows(workflow_dir=tmp_path)

    assert invalid == []
    assert any(wf.name == "with_secret" for wf in workflows)
    assert "interpolate_env: environment variable" not in caplog.text


def test_load_workflow_warns_for_missing_env_by_default(caplog, tmp_path: Path) -> None:
    workflow_path = tmp_path / "with_secret.yaml"
    workflow_path.write_text(
        """\
name: with_secret
description: Test interpolation warnings
steps:
  - name: notify
    type: output.slack_notify
    config:
      webhook_url: "${env:MISSING_WEBHOOK_URL}"
""",
        encoding="utf-8",
    )

    caplog.set_level("WARNING")
    caplog.clear()
    load_workflow("with_secret", workflow_dir=tmp_path)

    assert "interpolate_env: environment variable" in caplog.text


def test_load_config_reads_default_solux_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / ".config" / "solux" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[paths]
cache_dir = "~/.local/share/solux"
""".strip(),
        encoding="utf-8",
    )

    config = load_config()
    assert config.config_path == config_path.resolve()
    assert config.config_path.exists()
    assert config.paths.cache_dir == (tmp_path / ".local" / "share" / "solux").resolve()
