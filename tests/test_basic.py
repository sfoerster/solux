from __future__ import annotations

from pathlib import Path

from solus.cli import parse_args
from solus.config import ConfigError, load_config


def test_load_config_from_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[paths]
cache_dir = "~/custom-solus-cache"

[whisper]
threads = 3

[ollama]
model = "llama3.1:8b"

[triggers]
dir = "~/custom-solus-triggers"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.paths.cache_dir.name == "custom-solus-cache"
    assert config.whisper.threads == 3
    assert config.ollama.model == "llama3.1:8b"
    assert config.ffmpeg.binary == "ffmpeg"
    assert config.yt_dlp.binary == "yt-dlp"
    assert config.triggers_dir.name == "custom-solus-triggers"


def test_parse_args_defaults() -> None:
    args = parse_args(["episode.mp3"])
    assert args.command == "run"
    assert args.source == "episode.mp3"
    assert args.mode == "full"
    assert args.format == "markdown"
    assert args.output is None
    assert args.timestamps is False
    assert args.no_cache is False
    assert args.verbose is False


def test_parse_args_doctor_subcommand() -> None:
    args = parse_args(["doctor"])
    assert args.command == "doctor"
    assert args.workflow is None


def test_parse_args_doctor_with_workflow() -> None:
    args = parse_args(["doctor", "--workflow", "webpage_summary"])
    assert args.command == "doctor"
    assert args.workflow == "webpage_summary"


def test_parse_args_config_subcommand() -> None:
    args = parse_args(["config"])
    assert args.command == "config"


def test_parse_args_cleanup_subcommand() -> None:
    args = parse_args(
        [
            "cleanup",
            "--dry-run",
            "--yes",
            "--source-id",
            "abc123",
            "--finished-only",
            "--older-than-days",
            "30",
            "--jobs",
            "--jobs-stale-only",
            "--jobs-all-statuses",
        ]
    )
    assert args.command == "cleanup"
    assert args.dry_run is True
    assert args.yes is True
    assert args.source_id == "abc123"
    assert args.finished_only is True
    assert args.older_than_days == 30
    assert args.jobs is True
    assert args.jobs_stale_only is True
    assert args.jobs_all_statuses is True


def test_parse_args_serve_subcommand() -> None:
    args = parse_args(["serve", "--host", "127.0.0.1", "--port", "9000"])
    assert args.command == "serve"
    assert args.host == "127.0.0.1"
    assert args.port == 9000


def test_parse_args_ingest_subcommand() -> None:
    args = parse_args(["ingest", "a.mp3", "b.mp3", "--mode", "notes", "--format", "json", "--timestamps"])
    assert args.command == "ingest"
    assert args.sources == ["a.mp3", "b.mp3"]
    assert args.mode == "notes"
    assert args.format == "json"
    assert args.timestamps is True


def test_parse_args_log_subcommand() -> None:
    args = parse_args(["log", "--poll-interval", "1.5", "--no-history"])
    assert args.command == "log"
    assert args.poll_interval == 1.5
    assert args.no_history is True


def test_parse_args_run_model_flag() -> None:
    args = parse_args(["run", "ep.mp3", "--model", "llama3:8b"])
    assert args.command == "run"
    assert args.model == "llama3:8b"


def test_parse_args_ingest_model_flag() -> None:
    args = parse_args(["ingest", "a.mp3", "--model", "mistral:7b"])
    assert args.model == "mistral:7b"


def test_parse_args_worker_defaults_to_status() -> None:
    args = parse_args(["worker"])
    assert args.command == "worker"
    assert args.worker_action == "status"


def test_parse_args_worker_start_workers_flag() -> None:
    args = parse_args(["worker", "start", "--workers", "4", "--poll-interval", "1.25"])
    assert args.command == "worker"
    assert args.worker_action == "start"
    assert args.workers == 4
    assert args.poll_interval == 1.25


def test_parse_args_worker_stop_flags() -> None:
    args = parse_args(["worker", "stop", "--force", "--timeout", "3.5"])
    assert args.command == "worker"
    assert args.worker_action == "stop"
    assert args.force is True
    assert args.timeout == 3.5


def test_parse_args_retry_subcommand() -> None:
    args = parse_args(["retry"])
    assert args.command == "retry"
    assert args.job_ids is None


def test_parse_args_retry_with_job_ids() -> None:
    args = parse_args(["retry", "--job-id", "abc", "--job-id", "def"])
    assert args.command == "retry"
    assert args.job_ids == ["abc", "def"]


def test_parse_args_repair_subcommand() -> None:
    args = parse_args(["repair"])
    assert args.command == "repair"


def test_load_config_prompts_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[ollama]
model = "qwen3:8b"

[prompts]
system = "You are a pirate"
tldr = "Give me the gist"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.prompts.system == "You are a pirate"
    assert config.prompts.tldr == "Give me the gist"
    assert config.prompts.outline is None


def test_load_config_max_transcript_chars(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[ollama]
model = "qwen3:8b"
max_transcript_chars = 4000
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.ollama.max_transcript_chars == 4000


def test_load_config_security_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[security]
mode = "untrusted"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.security.mode == "untrusted"


def test_load_config_security_mode_invalid(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[security]
mode = "dangerous"
""".strip(),
        encoding="utf-8",
    )
    try:
        load_config(config_path)
    except Exception as exc:
        assert "Invalid security.mode value" in str(exc)
        return
    raise AssertionError("Expected load_config to reject invalid security.mode")


def test_load_config_webhook_rate_limit_invalid(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[security]
webhook_rate_limit = "nope"
""".strip(),
        encoding="utf-8",
    )
    try:
        load_config(config_path)
    except ConfigError as exc:
        assert "webhook_rate_limit" in str(exc)
        return
    raise AssertionError("Expected load_config to reject invalid security.webhook_rate_limit")


def test_build_logger_returns_isolated_instances() -> None:
    from solus.pipeline import _build_logger

    logger_a = _build_logger(None)
    logger_b = _build_logger(None)
    assert logger_a is not logger_b
    assert len(logger_a.handlers) == 1
    assert len(logger_b.handlers) == 1


def test_cmd_serve_passes_loaded_config_to_server(tmp_path: Path, monkeypatch) -> None:
    from argparse import Namespace
    from solus.cli.server import cmd_serve

    cfg_path = tmp_path / "config.toml"
    workflows_dir = tmp_path / "workflows"
    cfg_path.write_text(
        f"""
[paths]
cache_dir = "{tmp_path / "cache"}"

[workflows]
dir = "{workflows_dir}"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(cfg_path)
    monkeypatch.setattr("solus.cli.server.load_config", lambda: config)

    captured: dict[str, object] = {}

    def fake_run_serve(*, cache_dir, host, port, yt_dlp_binary, config, workflows_dir):
        captured["cache_dir"] = cache_dir
        captured["host"] = host
        captured["port"] = port
        captured["yt_dlp_binary"] = yt_dlp_binary
        captured["config"] = config
        captured["workflows_dir"] = workflows_dir
        return 0

    monkeypatch.setattr("solus.cli.server.run_serve", fake_run_serve)
    rc = cmd_serve(Namespace(host="127.0.0.1", port=9999))
    assert rc == 0
    assert captured["config"] is config
    assert captured["workflows_dir"] == config.workflows_dir
