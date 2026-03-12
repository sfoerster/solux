from __future__ import annotations

from pathlib import Path

import yaml

from solus.config import load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_load_config_uses_deployment_env_defaults(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("SOLUS_CACHE_DIR", "~/solus-cache-from-env")

    cfg = load_config(config_path)
    assert cfg.ollama.base_url == "http://ollama:11434"
    assert cfg.paths.cache_dir == Path("~/solus-cache-from-env").expanduser().resolve()


def test_load_config_prefers_toml_over_env_defaults(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[paths]
cache_dir = "~/cache-from-toml"

[ollama]
base_url = "http://from-toml:11434"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://from-env:11434")
    monkeypatch.setenv("SOLUS_CACHE_DIR", "~/cache-from-env")

    cfg = load_config(config_path)
    assert cfg.ollama.base_url == "http://from-toml:11434"
    assert cfg.paths.cache_dir == Path("~/cache-from-toml").expanduser().resolve()


def test_docker_compose_deployment_defaults_are_hardened() -> None:
    compose_path = _repo_root() / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    services = compose["services"]
    ollama = services["ollama"]
    server = services["server"]
    worker = services["worker"]

    assert ollama["image"] == "ollama/ollama:0.12.0"
    assert "127.0.0.1:11434:11434" in ollama["ports"]
    assert "127.0.0.1:8765:8765" in server["ports"]

    expected_config = "${SOLUS_CONFIG_MOUNT:-solus_config}:/home/solus/.config/solus"
    expected_data = "${SOLUS_DATA_MOUNT:-solus_data}:/home/solus/.local/share/solus"
    for service in (server, worker):
        assert expected_config in service["volumes"]
        assert expected_data in service["volumes"]


def test_systemd_units_use_portable_solus_lookup() -> None:
    server_unit = (_repo_root() / "contrib" / "systemd" / "solus-server.service").read_text(encoding="utf-8")
    worker_unit = (_repo_root() / "contrib" / "systemd" / "solus-worker.service").read_text(encoding="utf-8")

    assert "ExecStart=/usr/bin/env solus serve --host 127.0.0.1 --port 8765" in server_unit
    assert "ExecStart=/usr/bin/env solus worker start --_run-loop --workers 2" in worker_unit
    assert "/usr/bin/solus" not in server_unit
    assert "/usr/bin/solus" not in worker_unit


def test_tutorial_uses_valid_compose_bind_mount_example() -> None:
    tutorial = (_repo_root() / "docs" / "TUTORIAL.md").read_text(encoding="utf-8")

    assert "SOLUS_CONFIG_MOUNT=./my-config SOLUS_DATA_MOUNT=./my-data docker compose up -d" in tutorial
    assert "docker compose up -d \\\n  -v ./my-config:/home/solus/.config/solus" not in tutorial
